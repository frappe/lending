# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from lending.loan_management.doctype.process_loan_restructure_limit.process_loan_restructure_limit import (
	calculate_monthly_restructure_limit,
)
from lending.tests.test_utils import create_loan, make_loan_disbursement_entry
from lending.tests.utils import LendingTestSuite


class TestProcessLoanRestructureLimit(LendingTestSuite):
	def test_restructure_limit_is_logged_for_branch(self):
		branch = "_Test Restructure Limit Branch"
		if not frappe.db.exists("Branch", branch):
			frappe.get_doc({"doctype": "Branch", "branch": branch}).insert()

		frappe.db.set_value("Company", "_Test Company", "loan_restructure_limit", 10)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2026-09-28",
			posting_date="2026-08-14",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan.branch = branch
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-08-14", repayment_start_date="2026-09-28"
		)

		frappe.get_doc(
			{
				"doctype": "Loan Restructure",
				"loan": loan.name,
				"company": "_Test Company",
				"status": "Initiated",
				"docstatus": 1,
				"pending_principal_amount": 3000,
			}
		).db_insert()

		calculate_monthly_restructure_limit(branch=branch, posting_date="2026-08-31")

		log = frappe.get_all(
			"Loan Restructure Limit Log",
			{"branch": branch, "company": "_Test Company"},
			[
				"limit_percent",
				"principal_outstanding",
				"limit_amount",
				"in_process_limit",
				"available_limit",
			],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(log[0].limit_percent, 10)
		self.assertEqual(log[0].principal_outstanding, 100000)
		self.assertEqual(log[0].limit_amount, 10000)
		self.assertEqual(log[0].in_process_limit, 3000)
		self.assertEqual(log[0].available_limit, 7000)
