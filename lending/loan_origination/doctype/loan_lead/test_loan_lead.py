# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
import frappe.permissions
from frappe.utils import add_days, add_years, cint, getdate, now_datetime

from lending.loan_origination.doctype.loan_lead.loan_lead import (
	PAN_COUNTRY,
	REJECTED_WORKFLOW_STATE,
	validate_cooling_period,
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


class TestLoanLeadAge(LendingTestSuite):
	def test_an_applicant_whose_birthday_is_still_ahead_is_a_year_younger(self):
		# Turns 18 tomorrow, so 17 today. Subtracting the years alone would say 18.
		lead = make_loan_lead(
			email="age-tomorrow@example.com",
			date_of_birth=add_days(add_years(getdate(), -18), 1),
		)

		self.assertEqual(lead.age, 17)

	def test_an_applicant_whose_birthday_is_today_has_had_it(self):
		lead = make_loan_lead(
			email="age-today@example.com",
			date_of_birth=add_years(getdate(), -18),
		)

		self.assertEqual(lead.age, 18)

	def test_a_business_applicant_carries_no_age(self):
		lead = make_business_loan_lead("age-business@example.com", "+911234500601")

		self.assertEqual(lead.age, 0)

	def test_an_individual_turned_business_does_not_keep_the_age_it_had(self):
		lead = make_loan_lead(email="age-switch@example.com")
		self.assertGreater(lead.age, 0)

		lead.applicant_type = "Business"
		lead.company_name = "Age Switch Pvt Ltd"
		lead.save()

		self.assertEqual(lead.age, 0)

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
