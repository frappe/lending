# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from lending.loan_management.doctype.loan_restructure.test_loan_restructure import (
	create_loan_restructure,
)
from lending.loan_management.doctype.process_loan_restructure_limit.process_loan_restructure_limit import (
	calculate_monthly_restructure_limit,
)
from lending.tests.test_utils import create_loan, make_loan_disbursement_entry
from lending.tests.utils import LendingTestSuite


class TestProcessLoanRestructureLimit(LendingTestSuite):
	branch = "_Test Restructure Limit Branch"

	@classmethod
	def make_class_data(cls):
		if not frappe.db.exists("Branch", cls.branch):
			frappe.get_doc({"doctype": "Branch", "branch": cls.branch}).insert()

	def test_restructure_limit_log(self):
		frappe.db.set_value("Company", "_Test Company", "loan_restructure_limit", 25)

		loans = []
		for loan_amount, disbursed_amount in ((100000, 80000), (20000, 20000)):
			loan = create_loan(
				"_Test Customer 1",
				"Term Loan Product 4",
				loan_amount,
				"Repay Over Number of Periods",
				12,
				repayment_start_date="2026-09-28",
				posting_date="2026-08-14",
				rate_of_interest=8.5,
				applicant_type="Customer",
			)
			loan.branch = self.branch
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				disbursed_amount,
				disbursement_date="2026-08-14",
				repayment_start_date="2026-09-28",
			)
			loans.append(loan)

		partly_disbursed_loan, restructured_loan = loans

		# restructure taken while overdue, then the loan is no longer overdue
		frappe.db.set_value("Loan", restructured_loan.name, "days_past_due", 5)
		loan_restructure = create_loan_restructure(
			loan=restructured_loan.name, restructure_date="2026-08-20"
		)
		frappe.db.set_value("Loan", restructured_loan.name, "days_past_due", 0)

		calculate_monthly_restructure_limit(branch=self.branch, posting_date="2026-08-31")
		self.assert_logs(
			{
				"2026-08-31": {
					"principal_outstanding": 100000,
					"limit_amount": 25000,
					"utilized_limit": 0,
					"in_process_limit": 20000,
					"available_limit": 5000,
					"delinquent_in_process_limit": 20000,
					"delinquent_available_limit": 0,
				}
			}
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()
		frappe.get_doc(
			{
				"doctype": "Loan Balance Adjustment",
				"loan": partly_disbursed_loan.name,
				"company": "_Test Company",
				"posting_date": "2026-09-01",
				"adjustment_type": "Debit Adjustment",
				"adjustment_account": "Interest Income Account - _TC",
				"amount": 3000,
			}
		).submit()

		calculate_monthly_restructure_limit(branch=self.branch, posting_date="2026-09-30")

		# a back-dated run updates its own month only
		frappe.db.set_value("Loan", restructured_loan.name, "status", "Closed")
		calculate_monthly_restructure_limit(branch=self.branch, posting_date="2026-08-31")

		self.assert_logs(
			{
				"2026-08-31": {"principal_outstanding": 83000, "utilized_limit": 0},
				"2026-09-30": {
					"principal_outstanding": 103000,
					"utilized_limit": 20000,
					"in_process_limit": 0,
				},
			}
		)

	def assert_logs(self, expected):
		logs = frappe.get_all(
			"Loan Restructure Limit Log",
			{"branch": self.branch, "company": "_Test Company"},
			["*"],
		)
		self.assertEqual(sorted(str(log.date) for log in logs), sorted(expected))

		for log in logs:
			for fieldname, value in expected[str(log.date)].items():
				self.assertEqual(log[fieldname], value, f"{log.date} {fieldname}")
