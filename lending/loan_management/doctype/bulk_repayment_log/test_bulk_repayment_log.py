# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_months, get_datetime

from lending.loan_management.doctype.loan_repayment.loan_repayment import post_bulk_payments
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
)
from lending.tests.utils import LendingTestSuite


class TestBulkRepaymentLog(LendingTestSuite):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		master_init()
		init_loan_products()
		init_customers()

	def setUp(self):
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_bulk_repayment_logs(self):
		posting_date = get_datetime("2024-04-18")
		repayment_start_date = get_datetime("2024-05-05")
		loan_a = create_loan(
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
		loan_b = create_loan(
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
		loans = [loan_a, loan_b]
		for loan in loans:
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=posting_date,
				repayment_start_date=repayment_start_date,
			)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=add_months(posting_date, 5), company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=add_months(repayment_start_date, 5))

		data = []
		for i in range(5):
			data.append(
				{
					"against_loan": loan_a.name,
					"value_date": add_months(repayment_start_date, i),
					"amount_paid": 178025,
				}
			)
		# This should fail (closed loan)
		frappe.db.set_value("Loan", loan_b.name, "status", "Closed")
		for i in range(5):
			data.append(
				{
					"against_loan": loan_b.name,
					"value_date": add_months(repayment_start_date, i),
					"amount_paid": 178025,
				}
			)
		post_bulk_payments(data)

		successful_log = frappe.get_doc("Bulk Repayment Log", {"loan": loan_a.name})
		failed_log = frappe.get_doc("Bulk Repayment Log", {"loan": loan_b.name})

		self.assertEqual(successful_log.status, "Success")
		self.assertEqual(failed_log.status, "Failure")

	def test_bulk_payments_for_multiple_disbursements(self):
		posting_date = get_datetime("2024-04-18")
		repayment_start_date = get_datetime("2024-05-05")
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
		disbursement_a = make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount / 2,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)
		disbursement_b = make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount / 2,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date=add_months(posting_date, 5), company="_Test Company"
		)
		process_daily_loan_demands(loan=loan.name, posting_date=add_months(repayment_start_date, 5))

		data = []
		for i in range(5):
			data.append(
				{
					"against_loan": loan.name,
					"value_date": add_months(repayment_start_date, i),
					"amount_paid": 178025,
					"loan_disbursement": disbursement_a.name,
				}
			)
		# This should fail (closed disbursement)
		frappe.db.set_value("Loan Disbursement", disbursement_b.name, "status", "Closed")
		for i in range(5):
			data.append(
				{
					"against_loan": loan.name,
					"value_date": add_months(repayment_start_date, i),
					"amount_paid": 178025,
					"loan_disbursement": disbursement_b.name,
				}
			)
		post_bulk_payments(data)

		successful_log = frappe.get_doc("Bulk Repayment Log", {"loan_disbursement": disbursement_a.name})
		failed_log = frappe.get_doc("Bulk Repayment Log", {"loan_disbursement": disbursement_b.name})

		self.assertEqual(successful_log.status, "Success")
		self.assertEqual(failed_log.status, "Failure")

		self.assertEqual(
			len(
				frappe.db.get_all("Loan Repayment", {"docstatus": 1, "loan_disbursement": disbursement_a.name})
			),
			5,
		)
		self.assertFalse(
			frappe.db.exists("Loan Repayment", {"docstatus": 1, "loan_disbursement": disbursement_b.name})
		)
