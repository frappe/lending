# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
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
	create_loan_refund,
	create_repayment_entry,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)


class TestLoanRefund(IntegrationTestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_loan_closure_post_refund_with_excess_amount(self):
		set_loan_accrual_frequency("Daily")

		posting_date = "2024-04-05"
		repayment_start_date = "2024-05-05"

		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
		)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-05-04", company=loan.company
		)
		process_daily_loan_demands(loan=loan.name, posting_date="2024-05-05")

		repayment = create_repayment_entry(loan.name, "2024-05-05", 1020000)

		repayment.submit()

		create_loan_refund(loan.name, "2024-05-05", 4461.29, is_excess_amount_refund=1)

		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")
		self.assertEqual(loan.excess_amount_paid, 0)

		repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "docstatus": 1, "status": "Closed"},
			"name",
		)

		self.assertTrue(repayment_schedule, "Repayment schedule not closed after refund")

	def test_loan_closure_post_refund_with_security_amount(self):
		set_loan_accrual_frequency("Daily")

		posting_date = "2024-04-05"
		repayment_start_date = "2024-05-05"

		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			withhold_security_deposit=True,
		)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-05-04", company=loan.company
		)
		process_daily_loan_demands(loan=loan.name, posting_date="2024-05-05")

		repayment = create_repayment_entry(loan.name, "2024-05-05", 1015538.71)

		repayment.submit()

		create_loan_refund(loan.name, "2024-05-05", 178025, is_security_amount_refund=1)

		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")
		self.assertEqual(loan.excess_amount_paid, 0)

		repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "docstatus": 1, "status": "Closed"},
			"name",
		)

		self.assertTrue(repayment_schedule, "Repayment schedule not closed after refund")
