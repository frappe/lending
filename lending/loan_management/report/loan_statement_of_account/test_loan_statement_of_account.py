import frappe

from lending.loan_management.report.loan_statement_of_account.loan_statement_of_account import (
	execute,
	group_entries,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	make_loan_disbursement_entry,
)
from lending.tests.utils import LendingTestSuite


class TestLoanStatementOfAccount(LendingTestSuite):
	def test_loan_statement_of_account_validates_date_filters(self):
		filters = {"from_date": "2024-02-01", "to_date": "2024-01-01", "company": "_Test Company"}

		with self.assertRaises(frappe.ValidationError):
			execute(filters)

	def test_loan_statement_of_account_groups_entries(self):
		rows = [
			{"posting_date": "2024-01-01", "transaction_type": "EMI", "loan": "LOAN-1", "debit": 10, "credit": 0, "_sort_order": 1},
			{"posting_date": "2024-01-01", "transaction_type": "EMI", "loan": "LOAN-1", "debit": 5, "credit": 2, "_sort_order": 1},
		]

		grouped = group_entries(rows)
		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["debit"], 15)
		self.assertEqual(grouped[0]["credit"], 2)

	def test_loan_statement_of_account_returns_expected_rows(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			120000,
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
		repayment = create_repayment_entry(loan.name, "2024-02-05", 10000, loan_disbursement=disb.name)
		repayment.submit()

		report = execute(
			{
				"from_date": "2000-01-01",
				"to_date": "2099-12-31",
				"company": "_Test Company",
				"loan": loan.name,
			}
		)
		columns, data = report

		self.assertTrue(columns)
		self.assertTrue(data)

		disbursement_row = next(
			row for row in data if row.get("transaction_doctype") == "Loan Disbursement"
		)
		repayment_row = next(
			row for row in data if row.get("transaction_doctype") == "Loan Repayment"
		)

		expected_data = {
			"transaction_type": "Disbursement",
			"transaction_doctype": "Loan Disbursement",
			"transaction_name": disb.name,
			"loan": loan.name,
			"debit": 120000.0,
		}
		for key, value in expected_data.items():
			self.assertEqual(disbursement_row.get(key), value)

		expected_data = {
			"transaction_type": "Normal Repayment",
			"transaction_doctype": "Loan Repayment",
			"transaction_name": repayment.name,
			"loan": loan.name,
			"credit": 10000.0,
		}
		for key, value in expected_data.items():
			self.assertEqual(repayment_row.get(key), value)
