import unittest

import frappe
from frappe.utils import add_to_date, date_diff, flt, get_datetime, get_first_day, nowdate

from erpnext.selling.doctype.customer.test_customer import get_customer_dict

from lending.loan_management.doctype.loan.test_loan import (
	create_demand_loan,
	create_loan,
	create_loan_accounts,
	create_loan_application,
	create_loan_product,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	make_loan_disbursement_entry,
	set_loan_settings_in_company,
)
from lending.loan_management.doctype.loan_application.loan_application import create_pledge
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	days_in_year,
)
from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
	create_process_loan_classification,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_demand_loans,
	process_loan_interest_accrual_for_term_loans,
)


class TestLoanInterestAccrual(unittest.TestCase):
	def setUp(self):
		set_loan_settings_in_company()

		create_loan_accounts()

		create_loan_product(
			"Demand Loan",
			"Demand Loan",
			2000000,
			13.5,
			25,
			0,
			5,
			"Cash",
			"Disbursement Account - _TC",
			"Payment Account - _TC",
			"Loan Account - _TC",
			"Interest Income Account - _TC",
			"Penalty Income Account - _TC",
		)

		create_loan_product(
			product_code="Term Loan With DPD",
			product_name="Term Loan With DPD",
			maximum_loan_amount=2000000,
			rate_of_interest=10,
			penalty_interest_rate=25,
			is_term_loan=1,
			grace_period_in_days=5,
			disbursement_account="Disbursement Account - _TC",
			payment_account="Payment Account - _TC",
			loan_account="Loan Account - _TC",
			interest_income_account="Interest Income Account - _TC",
			penalty_income_account="Penalty Income Account - _TC",
			repayment_method="Repay Over Number of Periods",
			repayment_periods=12,
			repayment_schedule_type="Monthly as per repayment start date",
			days_past_due_threshold_for_npa=90,
		)

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price(
			"Test Security 1", 500, "Nos", get_datetime(), get_datetime(add_to_date(nowdate(), hours=24))
		)

		if not frappe.db.exists("Customer", "_Test Loan Customer"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer")).insert(ignore_permissions=True)

		self.applicant = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

		setup_loan_classification_ranges("_Test Company")

	def test_loan_interest_accural(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant, "Demand Loan", pledge
		)
		create_pledge(loan_application)
		loan = create_demand_loan(
			self.applicant, "Demand Loan", loan_application, posting_date=get_first_day(nowdate())
		)
		loan.submit()

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)
		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)
		loan_interest_accural = frappe.get_doc("Loan Interest Accrual", {"loan": loan.name})

		self.assertEqual(flt(loan_interest_accural.interest_amount, 0), flt(accrued_interest_amount, 0))

	def test_dpd_calculation(self):
		loan = create_loan(
			applicant=self.applicant,
			loan_product="Term Loan With DPD",
			loan_amount=1200000,
			repayment_method="Repay Over Number of Periods",
			repayment_periods=12,
			applicant_type="Customer",
			repayment_start_date="2023-01-31",
			posting_date="2023-01-01",
		)
		loan.submit()

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date="2023-02-01")
		process_loan_interest_accrual_for_term_loans(posting_date="2023-02-01")
		create_process_loan_classification(
			posting_date="2023-02-02", loan_product=loan.loan_product, loan=loan.name
		)

		loan_details = frappe.db.get_value(
			"Loan",
			loan.name,
			["days_past_due", "classification_code", "classification_name"],
			as_dict=1,
		)

		self.assertEqual(loan_details.days_past_due, 2)
		self.assertEqual(loan_details.classification_code, "SMA-0")
		self.assertEqual(loan_details.classification_name, "Special Mention Account - 0")

		create_process_loan_classification(
			posting_date="2023-04-05", loan_product=loan.loan_product, loan=loan.name
		)
		loan_details = frappe.db.get_value(
			"Loan",
			loan.name,
			["days_past_due", "classification_code", "classification_name"],
			as_dict=1,
		)

		self.assertEqual(loan_details.days_past_due, 64)
		self.assertEqual(loan_details.classification_code, "SMA-2")
		self.assertEqual(loan_details.classification_name, "Special Mention Account - 2")

		create_process_loan_classification(
			posting_date="2023-07-05", loan_product=loan.loan_product, loan=loan.name
		)
		loan_details = frappe.db.get_value(
			"Loan",
			loan.name,
			[
				"days_past_due",
				"classification_code",
				"classification_name",
				"is_npa",
				"manual_npa",
			],
			as_dict=1,
		)

		applicant_status = frappe.db.get_value("Customer", self.applicant, "is_npa")

		self.assertEqual(loan_details.days_past_due, 155)
		self.assertEqual(loan_details.classification_code, "D1")
		self.assertEqual(loan_details.classification_name, "Substandard Asset")
		self.assertEqual(loan_details.is_npa, 1)
		self.assertEqual(loan_details.manual_npa, 1)
		self.assertEqual(applicant_status, 1)

	def test_accumulated_amounts(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant, "Demand Loan", pledge
		)
		create_pledge(loan_application)
		loan = create_demand_loan(
			self.applicant, "Demand Loan", loan_application, posting_date=get_first_day(nowdate())
		)
		loan.submit()

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1
		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)
		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)
		loan_interest_accrual = frappe.get_doc("Loan Interest Accrual", {"loan": loan.name})

		self.assertEqual(flt(loan_interest_accrual.interest_amount, 0), flt(accrued_interest_amount, 0))

		next_start_date = "2019-10-31"
		next_end_date = "2019-11-29"

		no_of_days = date_diff(next_end_date, next_start_date) + 1
		process = process_loan_interest_accrual_for_demand_loans(posting_date=next_end_date)
		new_accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		total_pending_interest_amount = flt(accrued_interest_amount + new_accrued_interest_amount, 0)

		loan_interest_accrual = frappe.get_doc(
			"Loan Interest Accrual", {"loan": loan.name, "process_loan_interest_accrual": process}
		)
		self.assertEqual(
			flt(loan_interest_accrual.total_pending_interest_amount, 0), total_pending_interest_amount
		)


def setup_loan_classification_ranges(company):
	classification_ranges = [
		["SMA-0", "Special Mention Account - 0", 0, 30],
		["SMA-1", "Special Mention Account - 1", 31, 60],
		["SMA-2", "Special Mention Account - 2", 61, 90],
		["D1", "Substandard Asset", 91, 365],
		["D2", "Doubtful Asset", 366, 1098],
		["D3", "Loss Asset", 1099, 10000000],
	]
	company_doc = frappe.get_doc("Company", company)
	company_doc.set("loan_classification_ranges", [])

	for classification_range in classification_ranges:
		loan_classification = frappe.new_doc("Loan Classification")
		loan_classification.classification_code = classification_range[0]
		loan_classification.classification_name = classification_range[1]
		loan_classification.insert(ignore_if_duplicate=True)

		company_doc.append(
			"loan_classification_ranges",
			{
				"classification_code": classification_range[0],
				"min_dpd_range": classification_range[2],
				"max_dpd_range": classification_range[3],
			},
		)

	company_doc.save()
