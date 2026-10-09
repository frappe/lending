# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
import frappe.permissions
from frappe import _
from frappe.utils import cint, now_datetime

from lending.loan_origination.doctype.loan_lead.loan_lead import (
	MAX_BULK_OTP_LEADS,
	PAN_COUNTRY,
	TELEPHONY_APP,
	bulk_send_otp,
	get_enabled_otp_mediums,
	resolve_otp_request,
	send_otp,
	validate_otp_verification,
	verify_otp,
)
from lending.tests.utils import LendingTestSuite

TEST_EMAIL = "loan-lead-otp@example.com"
SWAPPED_EMAIL = "swapped-otp@example.com"
TEST_MOBILE = "+911234500011"
TEST_OTP = "123456"
IN_FLIGHT_ERROR = "changed while the OTP was in flight"

COOLING_PERIOD_DAYS = 30
SHORTER_COOLING_PERIOD_DAYS = 5

TEST_LOAN_PRODUCT = "Personal Loan"
OTHER_TEST_LOAN_PRODUCT = "Term Loan Product 1"

LOAN_LEAD_MODULE = "lending.loan_origination.doctype.loan_lead.loan_lead"
WORKFLOW_STATE_FIELD = "workflow_state"

LOAN_LEAD_WORKFLOW = "Loan Lead Workflow"
BASIC_RULES_TASKS = "Loan Lead Basic Rules"
LIVE_LOAN_LIMIT_SCRIPT = "Live loan limit validation for Loan Lead"
BASIC_RULES_ACTION = "Run Basic Rules"
REJECT_ACTION = "Reject"
INCOMING_WORKFLOW_STATE = "Incoming"
SCRUBBING_WORKFLOW_STATE = "Scrubbing"

TELEPHONY_RATE_LIMITER = "telephony.otp.enforce_rate_limit"










def enable_email_otp_in_telephony():
	settings = frappe.get_doc("TP OTP Settings")
	settings.update(
		{
			"enabled": 0,
			"enable_email_otp": 1,
			"otp_length": 6,
			"otp_expiry_in_seconds": 300,
			"otp_max_attempts": 3,
			"otp_message_template": "Your OTP is {otp}. It is valid for {expiry_minutes} minutes.",
			"email_otp_subject": "Your verification code",
		}
	)
	settings.save()
	frappe.clear_cache(doctype="TP OTP Settings")


def set_verification_mandatory():
	frappe.db.set_single_value("Loan Origination Settings", "otp_verification_mandatory", 1)
	frappe.clear_cache(doctype="Loan Origination Settings")


def lift_telephony_rate_limit(test):
	rate_limiter = patch(TELEPHONY_RATE_LIMITER)
	rate_limiter.start()
	test.addCleanup(rate_limiter.stop)


def activate_loan_lead_workflow(test):
	was_active = frappe.db.get_value("Workflow", LOAN_LEAD_WORKFLOW, "is_active")

	test.addCleanup(forget_cached_workflow)
	test.addCleanup(
		frappe.db.set_value, "Workflow", LOAN_LEAD_WORKFLOW, "is_active", was_active
	)

	frappe.db.set_value("Workflow", LOAN_LEAD_WORKFLOW, "is_active", 1)
	forget_cached_workflow()


def forget_cached_workflow():
	frappe.cache.hdel("workflow", "Loan Lead")


def set_product_cooling_period(test, loan_product, cooling_period_days):
	previous = frappe.db.get_value("Loan Product", loan_product, "cooling_period_days")
	test.addCleanup(
		frappe.db.set_value, "Loan Product", loan_product, "cooling_period_days", previous
	)
	frappe.db.set_value("Loan Product", loan_product, "cooling_period_days", cooling_period_days)


def set_script_live_loan_limit(test, maximum_live_loans):
	"""Turn the live loan limit on the way a site does it: in the Server Script.

	The shipped script passes 0, so the rule is off until someone edits that number.
	There is nowhere else to set it -- Loan Product does not carry a limit.
	"""
	previous = frappe.db.get_value("Server Script", LIVE_LOAN_LIMIT_SCRIPT, "script")

	test.addCleanup(frappe.clear_cache)
	test.addCleanup(
		frappe.db.set_value, "Server Script", LIVE_LOAN_LIMIT_SCRIPT, "script", previous
	)

	frappe.db.set_value(
		"Server Script",
		LIVE_LOAN_LIMIT_SCRIPT,
		"script",
		previous.replace(
			"maximum_live_loans = 0", f"maximum_live_loans = {cint(maximum_live_loans)}"
		),
	)
	frappe.clear_cache()


def reject(lead, rejected_on=None):
	frappe.db.set_value("Loan Lead", lead.name, "rejected_on", rejected_on or now_datetime())
	return lead


@contextmanager
def no_write_permission_on(doctype):
	"""Deny write on one doctype, leaving every other permission alone.

	Document.check_permission reaches frappe.permissions.has_permission through the
	module, so patching it there is what the real call actually goes through.
	"""

	def has_permission(dt, ptype="read", *args, **kwargs):
		return not (dt == doctype and ptype == "write")

	with patch.object(frappe.permissions, "has_permission", side_effect=has_permission):
		yield


@contextmanager
def in_workflow_state(lead, workflow_state):
	lead.set(WORKFLOW_STATE_FIELD, workflow_state)

	with (
		patch(f"{LOAN_LEAD_MODULE}.get_workflow_name", return_value="Loan Lead Workflow"),
		patch(
			f"{LOAN_LEAD_MODULE}.get_workflow_state_field",
			return_value=WORKFLOW_STATE_FIELD,
		),
	):
		yield lead


def make_loan_lead(
	email=TEST_EMAIL,
	mobile_number=TEST_MOBILE,
	pan=None,
	applicant_country=None,
	loan_product=TEST_LOAN_PRODUCT,
	date_of_birth="1990-01-01",
):
	return frappe.get_doc(
		{
			"doctype": "Loan Lead",
			"applicant_type": "Individual",
			"applicant_name": "Test OTP Applicant",
			"email": email,
			"mobile_number": mobile_number,
			"applicant_country": applicant_country or (PAN_COUNTRY if pan else None),
			"pan": pan,
			"date_of_birth": date_of_birth,
			"loan_product": loan_product,
			"loan_amount": 100000,
			"proposed_tenure": 12,
		}
	).insert()


def make_business_loan_lead(email, mobile_number, loan_product=TEST_LOAN_PRODUCT):
	return frappe.get_doc(
		{
			"doctype": "Loan Lead",
			"applicant_type": "Business",
			"applicant_name": "Test Business Applicant",
			"company_name": "Test Business Applicant Pvt Ltd",
			"email": email,
			"mobile_number": mobile_number,
			"loan_product": loan_product,
			"loan_amount": 100000,
			"proposed_tenure": 12,
		}
	).insert()


def get_status(lead, fieldname):
	return frappe.db.get_value("Loan Lead", lead.name, fieldname)












@contextmanager
def no_read_permission_on(doctype):

	def has_permission(dt, ptype="read", *args, **kwargs):
		return not (dt == doctype and ptype == "read")

	with patch.object(frappe.permissions, "has_permission", side_effect=has_permission):
		yield


class TestLoanLeadOTP(LendingTestSuite):
	def setUp(self):
		if TELEPHONY_APP not in frappe.get_installed_apps():
			self.skipTest("requires the Telephony app to be installed")

		enable_email_otp_in_telephony()
		lift_telephony_rate_limit(self)

		frappe.db.set_single_value(
			"Loan Origination Settings", {"otp_for_email": 1, "otp_for_sms": 0}
		)
		frappe.clear_cache(doctype="Loan Origination Settings")

		# Cached Singles would keep serving these to later tests in this process.
		self.addCleanup(frappe.clear_cache, doctype="Loan Origination Settings")
		self.addCleanup(frappe.clear_cache, doctype="TP OTP Settings")

	def test_send_otp_rejects_a_medium_that_is_not_enabled(self):
		lead = make_loan_lead()

		with self.assertRaises(frappe.ValidationError):
			send_otp(lead.name, "SMS")

	def test_unknown_medium_is_rejected(self):
		lead = make_loan_lead()

		for medium in ("Fax", "email", "", None):
			with self.assertRaises((frappe.ValidationError, TypeError)):
				send_otp(lead.name, medium)
			with self.assertRaises((frappe.ValidationError, TypeError)):
				verify_otp(lead.name, medium, TEST_OTP)

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_email_otp_is_sent_to_the_lead_and_verifies(self, mock_code, mock_dispatch):
		lead = make_loan_lead()

		result = send_otp(lead.name, "Email")

		self.assertTrue(result["sent"])
		self.assertEqual(get_status(lead, "email_verification_status"), "Initiated")

		self.assertEqual(mock_dispatch.call_args[0][0], TEST_EMAIL)
		self.assertEqual(
			frappe.db.get_value("TP OTP", {"recipient": TEST_EMAIL}, "purpose"),
			f"Loan Lead {lead.name}",
		)

		self.assertEqual(verify_otp(lead.name, "Email", TEST_OTP), {"verified": True})
		self.assertEqual(get_status(lead, "email_verification_status"), "Verified")

		with self.assertRaises(frappe.ValidationError):
			send_otp(lead.name, "Email")

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_wrong_otp_leaves_the_lead_unverified_and_spends_an_attempt(
		self, mock_code, mock_dispatch
	):
		lead = make_loan_lead()
		send_otp(lead.name, "Email")

		result = verify_otp(lead.name, "Email", "000000")

		self.assertFalse(result["verified"])
		self.assertEqual(get_status(lead, "email_verification_status"), "Initiated")
		self.assertEqual(
			frappe.db.get_value("TP OTP", {"recipient": TEST_EMAIL, "is_verified": 0}, "attempts"),
			1,
		)

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_otp_issued_for_one_lead_cannot_verify_another(self, mock_code, mock_dispatch):
		lead = make_loan_lead()
		other_lead = make_loan_lead()

		send_otp(lead.name, "Email")

		self.assertFalse(verify_otp(other_lead.name, "Email", TEST_OTP)["verified"])
		self.assertEqual(get_status(other_lead, "email_verification_status"), "Pending")

		self.assertEqual(verify_otp(lead.name, "Email", TEST_OTP), {"verified": True})

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_changing_a_recipient_resets_only_its_own_verification(self, mock_code, mock_dispatch):
		lead = make_loan_lead()
		send_otp(lead.name, "Email")
		verify_otp(lead.name, "Email", TEST_OTP)

		lead.db_set("mobile_verification_status", "Verified")
		lead.reload()

		lead.email = "changed-otp@example.com"
		lead.save()

		self.assertEqual(lead.email_verification_status, "Pending")
		self.assertEqual(lead.mobile_verification_status, "Verified")

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_otp_endpoints_require_write_access_to_the_lead(self, mock_code, mock_dispatch):
		lead = make_loan_lead()

		endpoints = (
			lambda: send_otp(lead.name, "Email"),
			lambda: verify_otp(lead.name, "Email", TEST_OTP),
		)

		with self.set_user("Guest"):
			for endpoint in endpoints:
				with self.assertRaises(frappe.PermissionError) as raised:
					endpoint()

				self.assertTrue(str(raised.exception))

		mock_dispatch.assert_not_called()

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_verified_status_cannot_be_written_by_the_client(self, mock_code, mock_dispatch):
		lead = make_loan_lead()

		lead.email_verification_status = "Verified"
		lead.mobile_verification_status = "Verified"
		lead.save()

		self.assertEqual(lead.email_verification_status, "Pending")
		self.assertEqual(lead.mobile_verification_status, "Pending")

		send_otp(lead.name, "Email")
		verify_otp(lead.name, "Email", TEST_OTP)
		lead.reload()

		lead.applicant_name = "Renamed Applicant"
		lead.save()

		self.assertEqual(lead.email_verification_status, "Verified")

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_a_copied_lead_starts_unverified(self, mock_code, mock_dispatch):
		lead = make_loan_lead()
		send_otp(lead.name, "Email")
		verify_otp(lead.name, "Email", TEST_OTP)
		lead.reload()

		copy = frappe.copy_doc(lead)
		copy.insert()

		self.assertEqual(copy.email_verification_status, "Pending")

	def test_otp_is_refused_once_the_lead_leaves_draft(self):
		lead = make_loan_lead()
		lead.submit()

		with self.assertRaises(frappe.ValidationError):
			send_otp(lead.name, "Email")

		lead.cancel()

		with self.assertRaises(frappe.ValidationError):
			send_otp(lead.name, "Email")

		self.assertEqual(get_status(lead, "email_verification_status"), "Pending")

	def test_only_enabled_mediums_are_reported(self):
		self.assertEqual(get_enabled_otp_mediums(), ["Email"])

		frappe.db.set_single_value("Loan Origination Settings", "otp_for_email", 0)
		frappe.clear_cache(doctype="Loan Origination Settings")

		self.assertEqual(get_enabled_otp_mediums(), [])

	def test_conversion_is_only_gated_where_the_site_asks_for_it(self):
		lead = make_loan_lead(email="otp-gate@example.com")

		validate_otp_verification(lead)

		set_verification_mandatory()

		with self.assertRaises(frappe.ValidationError):
			validate_otp_verification(lead)

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_conversion_gate_asks_only_about_enabled_mediums(self, mock_code, mock_dispatch):
		lead = make_loan_lead(email="otp-gate-enabled@example.com")
		set_verification_mandatory()

		send_otp(lead.name, "Email")
		verify_otp(lead.name, "Email", TEST_OTP)

		self.assertEqual(get_status(lead, "mobile_verification_status"), "Pending")

		validate_otp_verification(lead)

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_conversion_gate_does_not_trust_the_lead_it_is_handed(self, mock_code, mock_dispatch):
		lead = make_loan_lead(email="otp-gate-claimed@example.com")
		set_verification_mandatory()

		lead.email_verification_status = "Verified"

		with self.assertRaises(frappe.ValidationError):
			validate_otp_verification(lead)

	def test_bulk_send_otp_caps_the_batch(self):
		with self.assertRaises(frappe.ValidationError):
			bulk_send_otp([f"LN-LEAD-{i:05d}" for i in range(MAX_BULK_OTP_LEADS + 1)], "Email")

	def test_bulk_send_otp_is_not_a_way_to_send_one_lead_many_otps(self):
		with self.assertRaises(frappe.ValidationError):
			bulk_send_otp([{"applicant_name": "Test Exposure Applicant"}], "Email")

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_a_lead_repeated_down_the_batch_is_sent_one_otp(self, mock_code, mock_dispatch):
		lead = make_loan_lead(email="bulk-repeat@example.com")

		result = bulk_send_otp([lead.name] * MAX_BULK_OTP_LEADS, "Email")

		self.assertEqual(result["sent"], [lead.name])
		self.assertEqual(result["failed"], [])
		self.assertEqual(mock_dispatch.call_count, 1)

	@patch("telephony.email_otp.dispatch_email_otp")
	@patch("telephony.email_otp.generate_otp_code", return_value=TEST_OTP)
	def test_bulk_send_otp_leaves_nothing_behind_for_a_failed_lead(self, mock_code, mock_dispatch):
		good_lead = make_loan_lead(email="bulk-good@example.com")
		bad_lead = make_loan_lead(email="bulk-bad@example.com")

		mock_dispatch.side_effect = lambda email, *args, **kwargs: (
			frappe.throw(_("Delivery failed.")) if email == "bulk-bad@example.com" else None
		)

		result = bulk_send_otp([good_lead.name, bad_lead.name], "Email")

		self.assertEqual(result["sent"], [good_lead.name])
		self.assertEqual(len(result["failed"]), 1)
		self.assertEqual(result["failed"][0]["loan_lead"], bad_lead.name)
		self.assertTrue(result["failed"][0]["error"])

		self.assertFalse(frappe.db.exists("TP OTP", {"recipient": "bulk-bad@example.com"}))
		self.assertEqual(get_status(bad_lead, "email_verification_status"), "Pending")

		self.assertTrue(frappe.db.exists("TP OTP", {"recipient": "bulk-good@example.com"}))
		self.assertEqual(get_status(good_lead, "email_verification_status"), "Initiated")

class TestLoanLeadOTPRecipientRace(LendingTestSuite):
	# Telephony is mocked out whole here, so unlike the rest of the OTP tests these run
	# wherever lending does -- including CI, which installs no Telephony app. The in-flight
	# rules are the part of the flow that needs no provider to exercise.
	def setUp(self):
		frappe.db.set_single_value(
			"Loan Origination Settings", {"otp_for_email": 1, "otp_for_sms": 0}
		)
		frappe.clear_cache(doctype="Loan Origination Settings")

		# Cached Singles would keep serving these to later tests in this process.
		self.addCleanup(frappe.clear_cache, doctype="Loan Origination Settings")

	def test_a_send_in_flight_when_the_recipient_changes_does_not_mark_the_new_one_initiated(
		self,
	):
		lead = make_loan_lead()

		def swap_recipient_then_send(*args, **kwargs):
			frappe.db.set_value("Loan Lead", lead.name, "email", SWAPPED_EMAIL)
			return {"sent": True}

		with patch(f"{LOAN_LEAD_MODULE}.get_telephony_otp") as mock_get_otp:
			mock_get_otp.return_value.send_otp.side_effect = swap_recipient_then_send

			with self.assertRaises(frappe.ValidationError):
				send_otp(lead.name, "Email")

		self.assertEqual(get_status(lead, "email_verification_status"), "Pending")

	def test_a_verify_in_flight_when_the_recipient_changes_does_not_verify_the_new_one(self):
		lead = make_loan_lead()

		def swap_recipient_then_verify(*args, **kwargs):
			frappe.db.set_value("Loan Lead", lead.name, "email", SWAPPED_EMAIL)
			return {"verified": True}

		with patch(f"{LOAN_LEAD_MODULE}.get_telephony_otp") as mock_get_otp:
			mock_get_otp.return_value.verify_otp.side_effect = swap_recipient_then_verify

			with self.assertRaises(frappe.ValidationError):
				verify_otp(lead.name, "Email", TEST_OTP)

		self.assertEqual(get_status(lead, "email_verification_status"), "Pending")

	def test_a_verify_in_flight_does_not_ride_on_a_status_the_new_recipient_earned(self):
		lead = make_loan_lead()

		# The replacement recipient is verified by another request while this one is in
		# flight, so the status field on its own reads as this request's own success.
		def swap_recipient_and_verify_it(*args, **kwargs):
			frappe.db.set_value(
				"Loan Lead",
				lead.name,
				{"email": SWAPPED_EMAIL, "email_verification_status": "Verified"},
			)
			return {"verified": True}

		with patch(f"{LOAN_LEAD_MODULE}.get_telephony_otp") as mock_get_otp:
			mock_get_otp.return_value.verify_otp.side_effect = swap_recipient_and_verify_it

			with self.assertRaisesRegex(frappe.ValidationError, IN_FLIGHT_ERROR):
				verify_otp(lead.name, "Email", TEST_OTP)

		# The status the other request earned stands, since it belongs to the recipient the
		# lead now holds. Asserting the swap landed keeps the test from passing on a throw
		# raised before the side effect ever ran.
		self.assertEqual(frappe.db.get_value("Loan Lead", lead.name, "email"), SWAPPED_EMAIL)
		self.assertEqual(get_status(lead, "email_verification_status"), "Verified")

	def test_a_send_in_flight_does_not_ride_on_a_status_the_new_recipient_earned(self):
		lead = make_loan_lead()

		def swap_recipient_and_initiate_it(*args, **kwargs):
			frappe.db.set_value(
				"Loan Lead",
				lead.name,
				{"email": SWAPPED_EMAIL, "email_verification_status": "Initiated"},
			)
			return {"sent": True}

		with patch(f"{LOAN_LEAD_MODULE}.get_telephony_otp") as mock_get_otp:
			mock_get_otp.return_value.send_otp.side_effect = swap_recipient_and_initiate_it

			with self.assertRaisesRegex(frappe.ValidationError, IN_FLIGHT_ERROR):
				send_otp(lead.name, "Email")

		self.assertEqual(frappe.db.get_value("Loan Lead", lead.name, "email"), SWAPPED_EMAIL)
		self.assertEqual(get_status(lead, "email_verification_status"), "Initiated")

class TestLoanLeadOTPDoesNotLeakWhichLeadsExist(LendingTestSuite):
	def test_a_missing_lead_and_a_forbidden_lead_are_refused_alike(self):
		lead = make_loan_lead(email="otp-existence@example.com")

		with self.set_user("Guest"):
			with self.assertRaises(frappe.PermissionError) as forbidden:
				resolve_otp_request(lead.name, "Email")

			with self.assertRaises(frappe.PermissionError) as missing:
				resolve_otp_request("LN-LEAD-99999", "Email")

		self.assertEqual(
			str(forbidden.exception).replace(lead.name, "X"),
			str(missing.exception).replace("LN-LEAD-99999", "X"),
		)
