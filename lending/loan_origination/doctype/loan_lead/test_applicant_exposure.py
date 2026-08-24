# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.selling.doctype.customer.test_customer import get_customer_dict

from lending.loan_origination.doctype.loan_lead.applicant_exposure import (
	ADVERSE_LOAN_STATUSES,
	DEFAULT_MAXIMUM_LIVE_LOANS,
	LIVE_LOAN_STATUSES,
	get_applicant_exposure,
	get_live_loan_count,
	get_matching_customers,
	run_live_loan_limit_task,
	validate_live_loan_limit,
)
from lending.loan_origination.doctype.loan_lead.loan_lead import PAN_COUNTRY
from lending.tests.test_utils import create_loan
from lending.tests.utils import LendingTestSuite

LOAN_PRODUCT = "Personal Loan"

EMAIL = "exposure-applicant@example.com"
MOBILE = "+911234599001"
OTHER_EMAIL = "exposure-somebody-else@example.com"
OTHER_MOBILE = "+911234599002"
PAN = "ABCDE1234F"
OTHER_PAN = "ZYXWV9876E"


class TestApplicantExposureIdentity(LendingTestSuite):
	def test_a_customer_is_matched_by_email(self):
		customer = make_customer("_Test Exposure By Email", email=EMAIL, mobile=OTHER_MOBILE)
		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		self.assertEqual(get_matching_customers(lead), [customer])

	def test_a_customer_is_matched_by_mobile_number(self):
		customer = make_customer("_Test Exposure By Mobile", email=OTHER_EMAIL, mobile=MOBILE)
		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		self.assertEqual(get_matching_customers(lead), [customer])

	def test_an_indian_applicant_is_matched_by_pan_alone(self):
		customer = make_customer(
			"_Test Exposure By PAN", email=OTHER_EMAIL, mobile=OTHER_MOBILE, pan=PAN
		)
		lead = make_lead(email=EMAIL, mobile_number=MOBILE, pan=PAN, applicant_country=PAN_COUNTRY)

		self.assertEqual(get_matching_customers(lead), [customer])

	def test_contact_details_are_not_consulted_once_a_pan_identifies_the_applicant(self):
		make_customer("_Test Exposure Shared Address", email=EMAIL, mobile=MOBILE)
		lead = make_lead(email=EMAIL, mobile_number=MOBILE, pan=PAN, applicant_country=PAN_COUNTRY)

		self.assertEqual(get_matching_customers(lead), [])

	def test_a_different_pan_is_a_different_applicant(self):
		make_customer("_Test Exposure Other PAN", email=OTHER_EMAIL, mobile=OTHER_MOBILE, pan=OTHER_PAN)
		lead = make_lead(email=EMAIL, mobile_number=MOBILE, pan=PAN, applicant_country=PAN_COUNTRY)

		self.assertEqual(get_matching_customers(lead), [])

	def test_an_applicant_nothing_identifies_matches_nobody(self):
		lead = make_lead(email=EMAIL, mobile_number=MOBILE)
		lead.email = None
		lead.mobile_number = None

		self.assertEqual(get_matching_customers(lead), [])
		self.assertEqual(get_live_loan_count(lead), 0)

	def test_exposure_is_added_up_across_every_matching_customer(self):
		by_email = make_customer("_Test Exposure Split A", email=EMAIL, mobile=OTHER_MOBILE)
		by_mobile = make_customer("_Test Exposure Split B", email=OTHER_EMAIL, mobile=MOBILE)
		make_live_loan(by_email, "Disbursed")
		make_live_loan(by_mobile, "Disbursed")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)
		exposure = get_applicant_exposure(lead)

		self.assertCountEqual(exposure["matched_customers"], [by_email, by_mobile])
		self.assertEqual(exposure["live_loan_count"], 2)


class TestApplicantExposureWhichLoansCount(LendingTestSuite):
	def test_every_committed_status_is_live(self):
		# Spelled out, not read from LIVE_LOAN_STATUSES, so a missing status is noticed.
		committed = (
			"Sanctioned",
			"Partially Disbursed",
			"Disbursed",
			"Active",
			"Loan Closure Requested",
		)
		self.assertCountEqual(LIVE_LOAN_STATUSES, committed)

		customer = make_customer("_Test Exposure Statuses", email=EMAIL)
		for status in committed:
			make_live_loan(customer, status)

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		self.assertEqual(get_live_loan_count(lead), len(committed))

	def test_a_finished_loan_is_reported_as_history_and_not_as_live(self):
		adverse = ("Written Off", "Settled")
		self.assertCountEqual(ADVERSE_LOAN_STATUSES, adverse)

		customer = make_customer("_Test Exposure Finished", email=EMAIL)
		for status in adverse:
			make_live_loan(customer, status)
		make_live_loan(customer, "Closed")

		exposure = get_applicant_exposure(make_lead(email=EMAIL, mobile_number=MOBILE))

		self.assertEqual(exposure["live_loan_count"], 0)
		self.assertEqual(exposure["adverse_loan_count"], len(adverse))

	def test_a_loan_that_was_never_submitted_is_not_counted(self):
		customer = make_customer("_Test Exposure Draft", email=EMAIL)
		draft = create_loan(customer, LOAN_PRODUCT, 100000, "Repay Over Number of Periods", 12)
		frappe.db.set_value("Loan", draft.name, "status", "Disbursed", update_modified=False)

		self.assertEqual(get_live_loan_count(make_lead(email=EMAIL, mobile_number=MOBILE)), 0)

	def test_a_cancelled_loan_is_not_counted(self):
		customer = make_customer("_Test Exposure Cancelled", email=EMAIL)
		loan = make_live_loan(customer, "Disbursed")
		frappe.db.set_value("Loan", loan, "docstatus", 2, update_modified=False)

		self.assertEqual(get_live_loan_count(make_lead(email=EMAIL, mobile_number=MOBILE)), 0)

	def test_an_employee_loan_is_not_counted(self):
		customer = make_customer("_Test Exposure Employee", email=EMAIL)
		loan = make_live_loan(customer, "Disbursed")
		frappe.db.set_value("Loan", loan, "applicant_type", "Employee", update_modified=False)

		self.assertEqual(get_live_loan_count(make_lead(email=EMAIL, mobile_number=MOBILE)), 0)

	def test_somebody_elses_loan_is_not_counted(self):
		stranger = make_customer("_Test Exposure Stranger", email=OTHER_EMAIL, mobile=OTHER_MOBILE)
		make_live_loan(stranger, "Disbursed")

		self.assertEqual(get_live_loan_count(make_lead(email=EMAIL, mobile_number=MOBILE)), 0)


class TestApplicantExposureFigures(LendingTestSuite):
	def test_outstanding_is_the_principal_left_on_the_loan(self):
		customer = make_customer("_Test Exposure Outstanding", email=EMAIL)
		# 600000 - 100000 (unearned interest) - 150000 (repaid)
		make_live_loan(
			customer, "Disbursed", loan_amount=500000, total_payment=600000,
			total_interest_payable=100000, total_principal_paid=150000,
		)

		exposure = get_applicant_exposure(make_lead(email=EMAIL, mobile_number=MOBILE))

		self.assertEqual(exposure["total_sanctioned"], 500000)
		self.assertEqual(exposure["total_outstanding"], 350000)

	def test_an_overpaid_loan_does_not_cancel_out_a_loan_that_is_owed(self):
		customer = make_customer("_Test Exposure Overpaid", email=EMAIL)
		make_live_loan(
			customer, "Disbursed", total_payment=100000, total_interest_payable=0,
			total_principal_paid=100000 + 40000,   # overpaid by 40000
		)
		make_live_loan(
			customer, "Active", total_payment=200000, total_interest_payable=0,
			total_principal_paid=50000,            # 150000 genuinely owed
		)

		exposure = get_applicant_exposure(make_lead(email=EMAIL, mobile_number=MOBILE))

		self.assertEqual(exposure["total_outstanding"], 150000)

	def test_the_worst_arrears_and_every_npa_are_reported(self):
		customer = make_customer("_Test Exposure Arrears", email=EMAIL)
		make_live_loan(customer, "Active", days_past_due=12)
		make_live_loan(customer, "Active", days_past_due=97, is_npa=1)
		make_live_loan(customer, "Disbursed", days_past_due=0)

		exposure = get_applicant_exposure(make_lead(email=EMAIL, mobile_number=MOBILE))

		self.assertEqual(exposure["max_days_past_due"], 97)
		self.assertEqual(exposure["npa_count"], 1)

	def test_an_applicant_with_no_history_reports_zeroes(self):
		exposure = get_applicant_exposure(make_lead(email=EMAIL, mobile_number=MOBILE))

		self.assertEqual(exposure["live_loan_count"], 0)
		self.assertEqual(exposure["total_sanctioned"], 0)
		self.assertEqual(exposure["total_outstanding"], 0)
		self.assertEqual(exposure["max_days_past_due"], 0)
		self.assertEqual(exposure["npa_count"], 0)
		self.assertEqual(exposure["adverse_loan_count"], 0)
		self.assertEqual(exposure["matched_customers"], [])

	def test_the_count_is_reported_on_its_own_for_a_rule_to_read(self):
		customer = make_customer("_Test Exposure Count", email=EMAIL)
		make_live_loan(customer, "Disbursed")
		make_live_loan(customer, "Active")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		self.assertEqual(get_live_loan_count(lead), 2)
		self.assertEqual(get_live_loan_count(lead.name), 2)


class TestApplicantExposurePermissions(LendingTestSuite):
	def test_a_caller_who_cannot_read_the_lead_is_told_nothing(self):
		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")

		self.assertRaises(frappe.PermissionError, get_applicant_exposure, lead.name)


def make_lead(email, mobile_number, pan=None, applicant_country=None):
	return frappe.get_doc(
		{
			"doctype": "Loan Lead",
			"applicant_type": "Individual",
			"applicant_name": "Test Exposure Applicant",
			"email": email,
			"mobile_number": mobile_number,
			"applicant_country": applicant_country,
			"pan": pan,
			"date_of_birth": "1990-01-01",
			"loan_product": LOAN_PRODUCT,
			"loan_amount": 100000,
			"proposed_tenure": 12,
		}
	).insert()


def make_customer(customer_name, email=None, mobile=None, pan=None):
	if not frappe.db.exists("Customer", customer_name):
		frappe.get_doc(get_customer_dict(customer_name)).insert(ignore_permissions=True)

	# email_id and mobile_no are fetched from the primary contact, so save() would blank them.
	frappe.db.set_value(
		"Customer", customer_name, {"email_id": email, "mobile_no": mobile, "pan": pan},
		update_modified=False,
	)

	return customer_name


def make_live_loan(
	applicant,
	status,
	loan_amount=100000,
	total_payment=0,
	total_interest_payable=0,
	total_principal_paid=0,
	days_past_due=0,
	is_npa=0,
):
	loan = create_loan(applicant, LOAN_PRODUCT, loan_amount, "Repay Over Number of Periods", 12)
	loan.submit()

	frappe.db.set_value(
		"Loan",
		loan.name,
		{
			"status": status,
			"total_payment": total_payment,
			"total_interest_payable": total_interest_payable,
			"total_principal_paid": total_principal_paid,
			"days_past_due": days_past_due,
			"is_npa": is_npa,
		},
		update_modified=False,
	)

	return loan.name


class TestApplicantExposureLiveLoanLimit(LendingTestSuite):
	def test_the_rule_is_off_when_no_limit_is_asked_for(self):
		customer = make_customer("_Test Limit Off", email=EMAIL)
		for _ in range(3):
			make_live_loan(customer, "Disbursed")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		for maximum_live_loans in (0, None, ""):
			validate_live_loan_limit(lead, maximum_live_loans)

	def test_an_applicant_under_the_limit_is_let_through(self):
		customer = make_customer("_Test Limit Under", email=EMAIL)
		make_live_loan(customer, "Disbursed")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		validate_live_loan_limit(lead, 2)

	def test_an_applicant_at_the_limit_is_refused(self):
		customer = make_customer("_Test Limit At", email=EMAIL)
		for _ in range(2):
			make_live_loan(customer, "Disbursed")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		with self.assertRaises(frappe.ValidationError):
			validate_live_loan_limit(lead, 2)

	def test_the_refusal_does_not_report_how_many_loans_the_applicant_has(self):
		customer = make_customer("_Test Limit Quiet", email=EMAIL)
		for _ in range(4):
			make_live_loan(customer, "Disbursed")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		with self.assertRaises(frappe.ValidationError) as raised:
			validate_live_loan_limit(lead, 2)

		self.assertNotIn("4", str(raised.exception))

	def test_the_products_limit_wins_over_the_fallback(self):
		set_product_live_loan_limit(self, LOAN_PRODUCT, 2)
		customer = make_customer("_Test Limit Product", email=EMAIL)
		for _ in range(2):
			make_live_loan(customer, "Disbursed")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		with self.assertRaises(frappe.ValidationError):
			validate_live_loan_limit(lead, 10)

	def test_the_fallback_applies_where_the_product_asks_for_no_limit(self):
		set_product_live_loan_limit(self, LOAN_PRODUCT, 0)
		customer = make_customer("_Test Limit Fallback", email=EMAIL)
		for _ in range(2):
			make_live_loan(customer, "Disbursed")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		with self.assertRaises(frappe.ValidationError):
			validate_live_loan_limit(lead, 2)

	def test_the_workflow_task_takes_its_limit_from_the_server_not_the_caller(self):
		set_product_live_loan_limit(self, LOAN_PRODUCT, 0)
		customer = make_customer("_Test Limit Task", email=EMAIL)
		for _ in range(2):
			make_live_loan(customer, "Disbursed")

		lead = make_lead(email=EMAIL, mobile_number=MOBILE)

		self.assertEqual(DEFAULT_MAXIMUM_LIVE_LOANS, 0)
		run_live_loan_limit_task(lead)


class TestApplicantExposureIsNotReachableOverHTTP(LendingTestSuite):
	def test_nothing_that_reads_the_loan_book_is_whitelisted(self):
		# Whitelisting these would put the loan book behind a lead the caller can create.
		for method in (
			get_applicant_exposure,
			get_live_loan_count,
			validate_live_loan_limit,
			run_live_loan_limit_task,
		):
			self.assertNotIn(method, frappe.whitelisted, f"{method.__name__} is whitelisted")


def set_product_live_loan_limit(test, loan_product, maximum_live_loans):
	previous = frappe.db.get_value("Loan Product", loan_product, "maximum_live_loans")
	test.addCleanup(
		frappe.db.set_value, "Loan Product", loan_product, "maximum_live_loans", previous
	)
	frappe.db.set_value("Loan Product", loan_product, "maximum_live_loans", maximum_live_loans)
