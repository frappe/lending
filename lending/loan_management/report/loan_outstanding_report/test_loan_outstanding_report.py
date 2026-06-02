from lending.loan_management.report.loan_outstanding_report.loan_outstanding_report import (
	execute,
	get_chart_data,
	get_columns,
)
from lending.tests.test_utils import create_loan, make_loan_disbursement_entry
from lending.tests.utils import LendingTestSuite


class TestLoanOutstandingReport(LendingTestSuite):
	def test_loan_outstanding_report_returns_expected_row_and_chart(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			110000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			repayment_start_date="2024-02-05",
			posting_date="2024-01-05",
			rate_of_interest=10,
		)
		loan.submit()
		disb = make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)

		report = execute(
			{"company": "_Test Company", "loan": loan.name, "loan_disbursement": disb.name}
		)
		columns, data, _, chart = report
		self.assertEqual(columns[0].get("fieldname"), "loan")
		self.assertTrue(data)
		expected_data = {
			"loan": loan.name,
			"loan_disbursement": disb.name,
			"loan_product": "Term Loan Product 4",
			"applicant": "_Test Loan Customer",
		}
		for key, value in expected_data.items():
			self.assertEqual(data[0].get(key), value)
		self.assertGreaterEqual(data[0].get("pending_principal_amount") or 0, 0)
		self.assertIn("data", chart)

	def test_loan_outstanding_report_defines_columns(self):
		columns = get_columns()
		self.assertGreater(len(columns), 5)

	def test_loan_outstanding_report_calculates_chart_totals(self):
		chart = get_chart_data(
			[
				{"pending_principal_amount": 10, "principal_overdue": 2, "interest_overdue": 1},
				{"pending_principal_amount": 15, "principal_overdue": 3, "interest_overdue": 2},
			]
		)
		self.assertEqual(chart["data"]["datasets"][0]["values"], [25, 5, 3])
