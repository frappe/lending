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

	def test_restructure_limit_is_logged_for_branch(self):
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
		self.assertEqual(
			frappe.db.get_value("Loan", partly_disbursed_loan.name, "status"), "Partially Disbursed"
		)

		loan_restructure = create_loan_restructure(
			loan=restructured_loan.name, restructure_date="2026-08-20"
		)
		self.assertEqual(loan_restructure.status, "Initiated")
		self.assertEqual(loan_restructure.pending_principal_amount, 20000)

		calculate_monthly_restructure_limit(branch=self.branch, posting_date="2026-08-31")
		self.assert_limit_log(utilized_limit=0, in_process_limit=20000, available_limit=5000)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		calculate_monthly_restructure_limit(branch=self.branch, posting_date="2026-08-31")
		self.assert_limit_log(utilized_limit=20000, in_process_limit=0, available_limit=5000)

	def assert_limit_log(self, utilized_limit, in_process_limit, available_limit):
		log = frappe.get_all(
			"Loan Restructure Limit Log",
			{"branch": self.branch, "company": "_Test Company"},
			[
				"limit_percent",
				"principal_outstanding",
				"limit_amount",
				"utilized_limit",
				"in_process_limit",
				"available_limit",
			],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(log[0].limit_percent, 25)
		self.assertEqual(log[0].principal_outstanding, 100000)
		self.assertEqual(log[0].limit_amount, 25000)
		self.assertEqual(log[0].utilized_limit, utilized_limit)
		self.assertEqual(log[0].in_process_limit, in_process_limit)
		self.assertEqual(log[0].available_limit, available_limit)
