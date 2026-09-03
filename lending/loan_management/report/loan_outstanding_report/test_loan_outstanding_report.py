import frappe

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.report.loan_outstanding_report.loan_outstanding_report import (
	execute,
	get_chart_data,
	get_columns,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	make_loan_disbursement_entry,
)
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
			{
				"company": "_Test Company",
				"loan": loan.name,
				"loan_disbursement": disb.name,
				"as_on_date": "2024-12-31",
			}
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

	def test_loan_outstanding_report_requires_as_on_date(self):
		self.assertRaises(frappe.ValidationError, execute, {"company": "_Test Company"})

	def test_loan_outstanding_report_excludes_disbursement_after_as_on_date(self):
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

		# as_on_date before the disbursement date: the loan should not appear yet
		_, data, _, _ = execute(
			{
				"company": "_Test Company",
				"loan": loan.name,
				"loan_disbursement": disb.name,
				"as_on_date": "2024-01-04",
			}
		)
		self.assertFalse(data)

		# as_on_date on/after the disbursement date: the loan should appear
		_, data, _, _ = execute(
			{
				"company": "_Test Company",
				"loan": loan.name,
				"loan_disbursement": disb.name,
				"as_on_date": "2024-01-05",
			}
		)
		self.assertTrue(data)

	def test_loan_outstanding_report_ignores_repayments_after_as_on_date(self):
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

		repayment = create_repayment_entry(loan.name, "2024-03-01", 20000)
		repayment.submit()

		filters_before_repayment = {
			"company": "_Test Company",
			"loan": loan.name,
			"loan_disbursement": disb.name,
			"as_on_date": "2024-02-15",
		}
		filters_after_repayment = {
			**filters_before_repayment,
			"as_on_date": "2024-12-31",
		}

		_, data_before, _, _ = execute(filters_before_repayment)
		_, data_after, _, _ = execute(filters_after_repayment)

		self.assertEqual(data_before[0].get("principal_amount_paid"), 0)
		self.assertGreater(data_after[0].get("pending_principal_amount"), 0)
		self.assertGreater(
			data_before[0].get("pending_principal_amount"),
			data_after[0].get("pending_principal_amount"),
		)

	def test_loan_outstanding_report_shows_loan_closed_after_as_on_date(self):
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

		process_daily_loan_demands(posting_date="2024-07-05", loan=loan.name)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2024-07-05")[
			"payable_amount"
		]
		create_repayment_entry(loan.name, "2024-07-05", payable_amount).submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")

		# as_on_date before the closing repayment: the loan was still outstanding then,
		# so it must still show up even though its current status is "Closed".
		_, data, _, _ = execute(
			{
				"company": "_Test Company",
				"loan": loan.name,
				"loan_disbursement": disb.name,
				"as_on_date": "2024-03-01",
			}
		)
		self.assertTrue(data, "Loan should still appear for a date before it was closed")
		self.assertGreater(data[0].get("pending_principal_amount"), 0)

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
