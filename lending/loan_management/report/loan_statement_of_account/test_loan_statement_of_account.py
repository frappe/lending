import frappe
from frappe.utils import add_days, nowdate

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

		self.assertEqual(data[0]["transaction_type"], "Opening")
		self.assertEqual(data[0]["balance"], 0)

	def make_loan_with_activity(self):
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
		return loan

	def test_loan_statement_of_account_carries_opening_balance(self):
		loan = self.make_loan_with_activity()

		_, data = execute(
			{
				"from_date": "2024-02-01",
				"to_date": "2099-12-31",
				"company": "_Test Company",
				"loan": loan.name,
			}
		)
		opening, *entries, total, closing = data

		self.assertEqual(opening["transaction_type"], "Opening")
		self.assertEqual(opening["debit"], 120000)
		self.assertEqual(opening["balance"], 120000)
		self.assertFalse(any(row.get("transaction_doctype") == "Loan Disbursement" for row in entries))

		self.assertEqual(total["debit"], sum(row["debit"] for row in entries))
		self.assertEqual(total["credit"], sum(row["credit"] for row in entries))
		self.assertEqual(total["balance"], total["debit"] - total["credit"])
		self.assertEqual(closing["balance"], opening["balance"] + total["balance"])
		self.assertEqual(entries[-1]["balance"], closing["balance"])

		_, data = execute(
			{
				"from_date": add_days(nowdate(), 1),
				"to_date": "2099-12-31",
				"company": "_Test Company",
				"loan": loan.name,
			}
		)
		opening = data[0]

		self.assertEqual(opening["credit"], 0)
		self.assertEqual(opening["debit"], opening["balance"])
		self.assertLess(opening["balance"], 120000)

	def test_loan_statement_of_account_grouped_view_keeps_running_balance(self):
		loan = self.make_loan_with_activity()
		filters = {
			"from_date": "2024-02-01",
			"to_date": "2099-12-31",
			"company": "_Test Company",
			"loan": loan.name,
		}

		_, detailed = execute({**filters, "group_by": "Detailed"})
		_, grouped = execute({**filters, "group_by": "Grouped"})
		opening, *entries, total, closing = grouped

		self.assertTrue(entries)
		self.assertTrue(all(row.get("posting_date") for row in entries))
		self.assertEqual(opening["balance"], 120000)
		self.assertEqual(entries[0]["balance"], opening["balance"] + entries[0]["debit"] - entries[0]["credit"])
		self.assertEqual(entries[-1]["balance"], closing["balance"])
		self.assertEqual(closing["balance"], opening["balance"] + total["balance"])

		for summary_row in (0, -2, -1):
			for field in ("debit", "credit", "balance"):
				self.assertEqual(grouped[summary_row][field], detailed[summary_row][field])
