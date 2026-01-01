# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_loan,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)


class TestLoanRestructure(IntegrationTestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_loan_restructure_capitalization(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-04-05",
			posting_date="2024-02-20",
			rate_of_interest=8.5,
			applicant_type="Customer",
			penalty_charges_rate=36,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-02-20", repayment_start_date="2024-04-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-04-04", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2024-04-05")

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2024-04-10")

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-02-20",
				"value_date": "2024-02-20",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 5000}],
				"debit_to": "Processing Fee Receivable Account - _TC",
			}
		)
		sales_invoice.submit()

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-02-20",
				"value_date": "2024-02-20",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Documentation Charge", "qty": 1, "rate": 1000}],
			}
		)
		sales_invoice.submit()

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2024-04-11",
			interest_waiver_amount=500,
			penal_waiver_amount=10,
			other_charges_waiver=0,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		repayments = frappe.db.get_all(
			"Loan Repayment",
			filters={"loan_restructure": loan_restructure.name, "docstatus": 1},
			pluck="name",
		)

		self.assertEqual(len(repayments), 5)


def create_loan_restructure(
	loan,
	restructure_date,
	interest_waiver_amount,
	penal_waiver_amount,
	other_charges_waiver,
	treatment_of_normal_interest="Capitalize",
	treatment_of_penal_interest="Capitalize",
	treatment_of_other_charges="Capitalize",
):

	doc = frappe.new_doc("Loan Restructure")
	doc.loan = loan
	doc.restructure_date = restructure_date
	doc.interest_waiver_amount = interest_waiver_amount
	doc.penal_interest_waiver = penal_waiver_amount
	doc.other_charges_waiver = other_charges_waiver
	doc.restructure_type = "Normal Restructure"
	doc.treatment_of_normal_interest = treatment_of_normal_interest
	doc.treatment_of_penal_interest = treatment_of_penal_interest
	doc.treatment_of_other_charges = treatment_of_other_charges
	doc.submit()

	return doc
