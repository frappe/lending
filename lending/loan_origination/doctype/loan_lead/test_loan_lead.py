# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
import frappe.permissions
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, cint, getdate, now_datetime
from frappe.utils.safe_exec import is_safe_exec_enabled

from lending.loan_origination.doctype.loan_lead.loan_lead import (
	DEFAULT_COOLING_PERIOD_DAYS,
	MAX_BULK_OTP_LEADS,
	PAN_COUNTRY,
	REJECTED_WORKFLOW_STATE,
	TELEPHONY_APP,
	bulk_send_otp,
	get_enabled_otp_mediums,
	resolve_otp_request,
	run_cooling_period_task,
	send_otp,
	validate_cooling_period,
	validate_otp_verification,
	verify_otp,
)
from lending.loan_origination.doctype.loan_lead.test_applicant_exposure import (
	make_customer,
	make_live_loan,
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


class TestLoanLead(LendingTestSuite):
	pass


class TestLoanLeadCoolingPeriod(LendingTestSuite):
	def test_applicant_is_cooled_off_after_a_rejection(self):
		reject(make_loan_lead(email="cooling-same@example.com"))

		lead = make_loan_lead(email="cooling-same@example.com")

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_a_new_number_on_a_rejected_email_is_still_the_same_applicant(self):
		reject(make_loan_lead(email="cooling-email@example.com", mobile_number="+911234500101"))

		by_email = make_loan_lead(email="cooling-email@example.com", mobile_number="+911234500102")
		by_mobile = make_loan_lead(
			email="cooling-other@example.com", mobile_number="+911234500101"
		)

		for lead in (by_email, by_mobile):
			with self.assertRaises(frappe.ValidationError):
				validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_pan_recognises_an_indian_applicant_whose_contact_details_are_both_new(
		self,
	):
		reject(
			make_loan_lead(
				email="cooling-pan@example.com",
				mobile_number="+911234500201",
				pan="ABCDE1234F",
			)
		)

		lead = make_loan_lead(
			email="cooling-pan-new@example.com",
			mobile_number="+911234500202",
			pan="ABCDE1234F",
		)

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_a_different_pan_is_a_different_indian_applicant(self):
		reject(
			make_loan_lead(
				email="cooling-shared@example.com",
				mobile_number="+911234500401",
				pan="ABCDE1234F",
			)
		)

		lead = make_loan_lead(
			email="cooling-shared@example.com",
			mobile_number="+911234500401",
			pan="ZYXWV9876E",
		)

		validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_an_applicant_outside_india_is_recognised_by_contact_details_alone(self):
		reject(
			make_loan_lead(
				email="cooling-uk@example.com",
				mobile_number="+447911123456",
				applicant_country="United Kingdom",
			)
		)

		lead = make_loan_lead(
			email="cooling-uk-new@example.com",
			mobile_number="+447911123456",
			applicant_country="United Kingdom",
		)

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_an_indian_applicant_without_a_pan_falls_back_to_contact_details(self):
		reject(make_loan_lead(email="cooling-nopan@example.com", applicant_country=PAN_COUNTRY))

		lead = make_loan_lead(email="cooling-nopan@example.com", applicant_country=PAN_COUNTRY)

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_a_pan_identifies_the_applicant_where_the_country_was_never_set(self):
		reject(
			make_loan_lead(
				email="cooling-nocountry@example.com",
				mobile_number="+911234500501",
				pan="ABCDE1234F",
			)
		)

		lead = make_loan_lead(
			email="cooling-nocountry-new@example.com",
			mobile_number="+911234500502",
			pan="ABCDE1234F",
		)
		lead.applicant_country = None

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_a_cancelled_rejection_stops_cooling_the_applicant_off(self):
		rejected = reject(make_loan_lead(email="cooling-cancelled@example.com"))
		frappe.db.set_value("Loan Lead", rejected.name, "docstatus", 2)

		lead = make_loan_lead(email="cooling-cancelled@example.com")

		validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_an_amendment_is_not_cooled_off_by_the_rejection_it_amends(self):
		rejected = reject(make_loan_lead(email="cooling-amended@example.com"))
		frappe.db.set_value("Loan Lead", rejected.name, "docstatus", 2)

		amendment = make_loan_lead(email="cooling-amended@example.com")
		amendment.amended_from = rejected.name

		validate_cooling_period(amendment, COOLING_PERIOD_DAYS)

	def test_an_unrelated_applicant_is_not_cooled_off(self):
		reject(make_loan_lead(email="cooling-rejected@example.com", mobile_number="+911234500301"))

		lead = make_loan_lead(email="cooling-unrelated@example.com", mobile_number="+911234500302")

		validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_applicant_is_clear_once_the_cooling_period_has_passed(self):
		reject(
			make_loan_lead(email="cooling-old@example.com"),
			rejected_on=add_days(now_datetime(), -(COOLING_PERIOD_DAYS + 1)),
		)

		lead = make_loan_lead(email="cooling-old@example.com")

		validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_no_cooling_period_is_asked_for_lets_the_applicant_straight_back(self):
		reject(make_loan_lead(email="cooling-off@example.com"))

		lead = make_loan_lead(email="cooling-off@example.com")

		for cooling_period_days in (0, None, ""):
			validate_cooling_period(lead, cooling_period_days)

	def test_a_rejected_lead_does_not_cool_itself_off(self):
		lead = reject(make_loan_lead(email="cooling-self@example.com"))
		lead.reload()

		validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_the_products_cooling_period_applies_where_the_fallback_asks_for_none(self):
		set_product_cooling_period(self, TEST_LOAN_PRODUCT, COOLING_PERIOD_DAYS)
		reject(make_loan_lead(email="cooling-product@example.com"))

		lead = make_loan_lead(email="cooling-product@example.com")

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead, 0)

	def test_the_products_cooling_period_wins_over_a_longer_fallback(self):
		set_product_cooling_period(self, TEST_LOAN_PRODUCT, SHORTER_COOLING_PERIOD_DAYS)
		reject(
			make_loan_lead(email="cooling-product-shorter@example.com"),
			rejected_on=add_days(now_datetime(), -(SHORTER_COOLING_PERIOD_DAYS + 1)),
		)

		lead = make_loan_lead(email="cooling-product-shorter@example.com")

		validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_the_fallback_applies_where_the_product_asks_for_none(self):
		set_product_cooling_period(self, TEST_LOAN_PRODUCT, 0)
		reject(make_loan_lead(email="cooling-product-none@example.com"))

		lead = make_loan_lead(email="cooling-product-none@example.com")

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead, COOLING_PERIOD_DAYS)

	def test_the_cooling_period_comes_from_the_product_being_applied_for(self):
		set_product_cooling_period(self, TEST_LOAN_PRODUCT, 0)
		set_product_cooling_period(self, OTHER_TEST_LOAN_PRODUCT, COOLING_PERIOD_DAYS)
		reject(
			make_loan_lead(
				email="cooling-other-product@example.com", loan_product=TEST_LOAN_PRODUCT
			)
		)

		lead = make_loan_lead(
			email="cooling-other-product@example.com", loan_product=OTHER_TEST_LOAN_PRODUCT
		)

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead, 0)

	def test_a_lead_named_over_frappe_call_is_the_lead_that_is_checked(self):
		reject(make_loan_lead(email="cooling-by-name@example.com"))

		lead = make_loan_lead(email="cooling-by-name@example.com")

		with self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead.name, COOLING_PERIOD_DAYS)

	def test_rejection_is_stamped_on_arriving_in_the_rejected_state(self):
		lead = make_loan_lead(email="cooling-stamp@example.com")

		with in_workflow_state(lead, REJECTED_WORKFLOW_STATE):
			lead.set_rejected_on()
			self.assertIsNotNone(lead.rejected_on)

			stamped = lead.rejected_on
			lead.set_rejected_on()

		self.assertEqual(lead.rejected_on, stamped)

	def test_leaving_the_rejected_state_clears_the_stamp(self):
		lead = make_loan_lead(email="cooling-reopened@example.com")
		lead.rejected_on = now_datetime()

		with in_workflow_state(lead, "Incoming"):
			lead.set_rejected_on()

		self.assertIsNone(lead.rejected_on)

	def test_nothing_is_stamped_or_cleared_without_an_active_workflow(self):
		lead = make_loan_lead(email="cooling-no-workflow@example.com")
		lead.rejected_on = now_datetime()

		with patch(f"{LOAN_LEAD_MODULE}.get_workflow_name", return_value=None):
			lead.set_rejected_on()

		self.assertIsNotNone(lead.rejected_on)


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


class TestLoanLeadCoolingPeriodIsGatedOnWritePermission(LendingTestSuite):
	def test_the_rule_is_callable_so_a_site_script_can_run_it(self):
		# The shipped Server Script calls this; un-whitelisting it would close the only
		# place a site can change the rule without forking the app.
		self.assertIn(validate_cooling_period, frappe.whitelisted)

	def test_only_post_reaches_it(self):
		allowed = frappe.allowed_http_methods_for_whitelisted_func[validate_cooling_period]
		self.assertEqual(tuple(allowed), ("POST",))

	def test_a_guest_cannot_reach_it(self):
		self.assertNotIn(validate_cooling_period, frappe.guest_methods)

	def test_the_task_wrapper_stays_unreachable_over_http(self):
		# The wrapper hardcodes the server's window; exposing it buys nothing and the
		# script path already covers the customisable case.
		self.assertNotIn(run_cooling_period_task, frappe.whitelisted)

	def test_a_caller_who_cannot_write_the_lead_is_refused(self):
		# Otherwise the rule is a lookup on any identity the caller names.
		reject(make_loan_lead(email="cooling-perm@example.com"))
		lead = make_loan_lead(email="cooling-perm@example.com")

		with no_write_permission_on("Loan Lead"), self.assertRaises(frappe.PermissionError):
			validate_cooling_period(lead.name, COOLING_PERIOD_DAYS)

	def test_the_workflow_task_takes_its_window_from_the_server_not_the_caller(self):
		reject(make_loan_lead(email="cooling-task@example.com"))
		lead = make_loan_lead(email="cooling-task@example.com")

		self.assertEqual(DEFAULT_COOLING_PERIOD_DAYS, 30)

		with self.assertRaises(frappe.ValidationError):
			run_cooling_period_task(lead)

	def test_the_refusal_names_no_lead_and_no_date(self):
		# reject() stamps the column, so the stamp is read back to compare against
		rejected = reject(make_loan_lead(email="cooling-quiet@example.com"))
		rejected.reload()

		lead = make_loan_lead(email="cooling-quiet@example.com")

		with self.assertRaises(frappe.ValidationError) as raised:
			run_cooling_period_task(lead)

		message = str(raised.exception)
		self.assertNotIn(rejected.name, message)
		self.assertNotIn(str(rejected.rejected_on.year), message)


class TestLoanLeadWorkflowTransition(LendingTestSuite):
	def setUp(self):
		if not frappe.db.exists("Workflow", LOAN_LEAD_WORKFLOW):
			self.skipTest("requires the Loan Lead Workflow fixture")

		if not frappe.db.exists("Workflow Transition Tasks", BASIC_RULES_TASKS):
			self.skipTest("requires the Loan Lead Basic Rules fixture")

		if not is_safe_exec_enabled():
			self.skipTest("the transition runs a Server Script, which needs server_script_enabled")

		activate_loan_lead_workflow(self)

	def test_a_new_lead_starts_in_the_first_state(self):
		lead = make_loan_lead(email="workflow-new@example.com")

		self.assertEqual(lead.get(WORKFLOW_STATE_FIELD), INCOMING_WORKFLOW_STATE)
		self.assertIsNone(lead.rejected_on)

	def test_rejecting_through_the_workflow_stamps_the_rejection(self):
		lead = make_loan_lead(email="workflow-rejected@example.com")

		apply_workflow(lead, REJECT_ACTION)
		lead.reload()

		self.assertEqual(lead.get(WORKFLOW_STATE_FIELD), REJECTED_WORKFLOW_STATE)
		self.assertTrue(lead.rejected_on)

	def test_a_clear_applicant_advances_through_the_transition(self):
		lead = make_loan_lead(email="workflow-clear@example.com")

		apply_workflow(lead, BASIC_RULES_ACTION)
		lead.reload()

		self.assertEqual(lead.get(WORKFLOW_STATE_FIELD), SCRUBBING_WORKFLOW_STATE)

	def test_the_transition_runs_the_cooling_period_rule(self):
		apply_workflow(make_loan_lead(email="workflow-cooling@example.com"), REJECT_ACTION)

		lead = make_loan_lead(email="workflow-cooling@example.com")

		with self.assertRaises(frappe.ValidationError):
			apply_workflow(lead, BASIC_RULES_ACTION)

		lead.reload()
		self.assertEqual(lead.get(WORKFLOW_STATE_FIELD), INCOMING_WORKFLOW_STATE)

	def test_the_transition_runs_the_live_loan_limit_rule(self):
		customer = make_customer(
			"_Test Workflow Live Loan Applicant", email="workflow-live@example.com"
		)
		make_live_loan(customer, "Active")
		set_script_live_loan_limit(self, 1)

		lead = make_loan_lead(email="workflow-live@example.com")

		with self.assertRaises(frappe.ValidationError):
			apply_workflow(lead, BASIC_RULES_ACTION)

		lead.reload()
		self.assertEqual(lead.get(WORKFLOW_STATE_FIELD), INCOMING_WORKFLOW_STATE)

	def test_a_business_applicant_clears_the_age_rule(self):
		lead = make_business_loan_lead("workflow-business@example.com", "+911234500301")

		apply_workflow(lead, BASIC_RULES_ACTION)
		lead.reload()

		self.assertEqual(lead.get(WORKFLOW_STATE_FIELD), SCRUBBING_WORKFLOW_STATE)

	def test_an_underage_applicant_is_stopped_by_the_transition(self):
		lead = make_loan_lead(
			email="workflow-underage@example.com",
			date_of_birth=add_days(getdate(), -365 * 10),
		)

		self.assertLess(lead.age, 18)

		with self.assertRaises(frappe.ValidationError):
			apply_workflow(lead, BASIC_RULES_ACTION)

		lead.reload()
		self.assertEqual(lead.get(WORKFLOW_STATE_FIELD), INCOMING_WORKFLOW_STATE)


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
