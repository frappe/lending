import frappe

from lending.loan_management.report.future_cashflow_report.future_cashflow_report import (
	execute,
	get_data,
)
from lending.tests.test_utils import create_loan, make_loan_disbursement_entry
from lending.tests.utils import LendingTestSuite


class TestFutureCashflowReport(LendingTestSuite):
	def test_future_cashflow_report_validates_required_filters(self):
		with self.assertRaises(frappe.ValidationError):
			get_data({"as_on_date": "2024-01-01"})

		with self.assertRaises(frappe.ValidationError):
			get_data({"company": "_Test Company"})

	def test_future_cashflow_report_returns_expected_loan_rows(self):
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

		report = execute(
			{
				"company": "_Test Company",
				"as_on_date": "2024-01-01",
				"loan": loan.name,
				"loan_disbursement": disb.name,
			}
		)
		columns, data = report

		self.assertEqual(columns[0].get("fieldname"), "loan")
		self.assertTrue(data)
		expected_data = {
			"loan": loan.name,
			"loan_disbursement": disb.name,
			"loan_product": "Term Loan Product 4",
		}
		for row in data:
			for key, value in expected_data.items():
				self.assertEqual(row.get(key), value)
		self.assertTrue(all(str(row.get("payment_date")) >= "2024-01-01" for row in data))
