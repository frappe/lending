import frappe

from lending.loan_management.report.past_cashflow_report.past_cashflow_report import (
	execute,
	get_data,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	make_loan_disbursement_entry,
)
from lending.tests.utils import LendingTestSuite


class TestPastCashflowReport(LendingTestSuite):
	def test_past_cashflow_report_validates_required_filters(self):
		with self.assertRaises(frappe.ValidationError):
			get_data({})

	def test_past_cashflow_report_returns_expected_aggregated_row(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			90000,
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
		repayment = create_repayment_entry(loan.name, "2024-02-05", 12000, loan_disbursement=disb.name)
		repayment.submit()

		report = execute(
			{"as_on_date": "2099-12-31", "company": "_Test Company", "loan": loan.name}
		)
		columns, data = report

		self.assertEqual(columns[0].get("fieldname"), "loan")
		self.assertEqual(len(data), 1)
		expected_data = {
			"loan": loan.name,
			"applicant": "_Test Loan Customer",
			"loan_product": "Term Loan Product 4",
		}
		for key, value in expected_data.items():
			self.assertEqual(data[0].get(key), value)
		self.assertGreater(frappe.utils.flt(data[0].get("principal_amount")), 0)
