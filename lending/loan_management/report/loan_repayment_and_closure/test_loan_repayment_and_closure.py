import frappe

from lending.loan_management.report.loan_repayment_and_closure.loan_repayment_and_closure import (
	execute,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	make_loan_disbursement_entry,
)
from lending.tests.utils import LendingTestSuite


class TestLoanRepaymentAndClosure(LendingTestSuite):
	def test_loan_repayment_and_closure_returns_expected_row(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			repayment_start_date="2024-02-05",
			posting_date="2024-01-05",
			rate_of_interest=12,
		)
		loan.submit()

		disb = make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)
		repayment = create_repayment_entry(loan.name, "2024-02-05", 15000, loan_disbursement=disb.name)
		repayment.submit()

		report = execute({"company": "_Test Company", "loan": loan.name})
		columns, data = report

		self.assertTrue(len(columns) > 0)
		self.assertTrue(data)
		row = data[0]
		expected_data = {
			"against_loan": loan.name,
			"loan_repayment": repayment.name,
			"applicant": "_Test Loan Customer",
			"repayment_type": "Normal Repayment",
		}
		for key, value in expected_data.items():
			self.assertEqual(row.get(key), value)
		self.assertGreaterEqual(frappe.utils.flt(row.get("amount_paid")), 15000)
