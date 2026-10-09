# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
import frappe.permissions
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, cint, getdate, now_datetime
from frappe.utils.safe_exec import is_safe_exec_enabled

from lending.loan_origination.doctype.loan_lead.loan_lead import (
	DEFAULT_COOLING_PERIOD_DAYS,
	PAN_COUNTRY,
	REJECTED_WORKFLOW_STATE,
	convert_to_loan_application,
	run_cooling_period_task,
	validate_cooling_period,
)
from lending.loan_origination.doctype.loan_lead.test_applicant_exposure import (
	as_a_direct_api_call,
	as_a_workflow_task,
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

class TestTheCoolingPeriodRuleIsNotAPlainEndpoint(LendingTestSuite):
	def test_a_direct_api_call_is_refused(self):
		lead = make_loan_lead(email="cooling-direct@example.com")

		with as_a_direct_api_call(), self.assertRaises(frappe.PermissionError):
			validate_cooling_period(lead.name, COOLING_PERIOD_DAYS)

	def test_the_workflow_task_still_reaches_it(self):
		reject(make_loan_lead(email="cooling-task-path@example.com"))
		lead = make_loan_lead(email="cooling-task-path@example.com")

		with as_a_workflow_task(), self.assertRaises(frappe.ValidationError):
			validate_cooling_period(lead.name, COOLING_PERIOD_DAYS)

class TestConversionIsAWorkflowTaskOnly(LendingTestSuite):
	def test_it_is_not_whitelisted(self):
		self.assertNotIn(convert_to_loan_application, frappe.whitelisted)

	def test_a_caller_who_cannot_read_the_lead_is_refused(self):
		lead = make_loan_lead(email="convert-perm@example.com")

		with no_read_permission_on("Loan Lead"), self.assertRaises(frappe.PermissionError):
			convert_to_loan_application(lead)
