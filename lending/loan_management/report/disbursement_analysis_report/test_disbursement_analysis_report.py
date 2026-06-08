# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.loan_management.report.disbursement_analysis_report.disbursement_analysis_report import (
	execute,
	get_columns,
	get_data,
)
from lending.tests.test_utils import create_loan, make_loan_disbursement_entry
from lending.tests.utils import LendingTestSuite


class TestDisbursementAnalysisReport(LendingTestSuite):
	def test_disbursement_analysis_report_returns_expected_rows(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			100000,
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
			loan_disbursement_charges=[{"charge": "Processing Fee", "amount": 5000}],
		)

		columns, data = execute(
			{"company": "_Test Company", "loan": loan.name, "loan_disbursement": disb.name}
		)

		self.assertTrue(data)
		self.assertEqual(columns[0].get("fieldname"), "loan_account")

		row = data[0]
		self.assertEqual(row.get("loan_account"), loan.name)
		self.assertEqual(row.get("loan_disbursement_id"), disb.name)
		self.assertEqual(row.get("applicant"), "_Test Loan Customer")
		self.assertEqual(row.get("applicant_type"), "Customer")
		self.assertEqual(row.get("interest_rate"), 10)
		self.assertEqual(row.get("disbursed_amount"), 100000)
		self.assertEqual(row.get("charge_type"), "Processing Fee")
		self.assertEqual(row.get("charge_amount"), 5000)
		self.assertIsNotNone(row.get("maturity_date"))

	def test_disbursement_analysis_report_assigns_tranche_numbers_in_order(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			repayment_start_date="2024-08-05",
			posting_date="2024-07-01",
			rate_of_interest=10,
		)
		loan.submit()

		# Created out of chronological order; report should reflect tranche sequencing by date.
		make_loan_disbursement_entry(
			loan.name, 50000, disbursement_date="2024-07-15", repayment_start_date="2024-08-05"
		)
		make_loan_disbursement_entry(
			loan.name, 30000, disbursement_date="2024-07-20", repayment_start_date="2024-08-05"
		)
		make_loan_disbursement_entry(
			loan.name, 20000, disbursement_date="2024-07-10", repayment_start_date="2024-08-05"
		)

		columns, data = execute({"company": "_Test Company", "loan": loan.name})

		# Ordered by disbursement_date, so tranche numbers should ascend 1, 2, 3.
		tranche_numbers = [row.get("tranche_number") for row in data]
		self.assertEqual(tranche_numbers, [1, 2, 3])

		disbursement_dates = [row.get("disbursement_date") for row in data]
		self.assertEqual(disbursement_dates, sorted(disbursement_dates))

	def test_disbursement_analysis_report_filters_by_applicant_type(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			repayment_start_date="2024-02-05",
			posting_date="2024-01-05",
			rate_of_interest=10,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)

		data = get_data({"company": "_Test Company", "applicant_type": "Customer", "loan": loan.name})
		self.assertTrue(data)
		self.assertTrue(all(row.get("applicant_type") == "Customer" for row in data))

		# No Employee applicants exist for this loan, so the result set should be empty.
		empty = get_data(
			{"company": "_Test Company", "applicant_type": "Employee", "loan": loan.name}
		)
		self.assertEqual(empty, [])

	def test_disbursement_analysis_report_defines_columns(self):
		columns = get_columns()
		fieldnames = [c.get("fieldname") for c in columns]
		self.assertIn("loan_account", fieldnames)
		self.assertIn("tranche_number", fieldnames)
		self.assertIn("disbursed_amount", fieldnames)
		self.assertIn("charge_amount", fieldnames)
