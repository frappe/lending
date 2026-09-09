import frappe
from frappe.utils import nowdate

from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	calculate_amounts,
	get_pending_principal_amount,
)
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
	def make_loan_and_disbursement(self):
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
		return loan, disb

	def run_report(self, loan, disb, as_on_date):
		_, data, _, chart = execute(
			{
				"company": "_Test Company",
				"loan": loan.name,
				"loan_disbursement": disb.name,
				"as_on_date": as_on_date,
			}
		)
		return data, chart

	def test_loan_outstanding_report_returns_expected_row_and_chart(self):
		loan, disb = self.make_loan_and_disbursement()

		data, chart = self.run_report(loan, disb, "2024-12-31")
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

	def test_loan_outstanding_report_reflects_as_on_date_snapshot(self):
		loan, disb = self.make_loan_and_disbursement()

		data, _ = self.run_report(loan, disb, "2024-01-04")
		self.assertFalse(data)

		create_repayment_entry(loan.name, "2024-03-01", 20000).submit()
		data_before, _ = self.run_report(loan, disb, "2024-02-15")
		data_after, _ = self.run_report(loan, disb, "2024-12-31")
		self.assertEqual(data_before[0].get("principal_amount_paid"), 0)
		self.assertGreater(
			data_before[0].get("pending_principal_amount"),
			data_after[0].get("pending_principal_amount"),
		)

	def test_loan_outstanding_report_shows_loan_closed_after_as_on_date(self):
		loan, disb = self.make_loan_and_disbursement()

		process_daily_loan_demands(posting_date="2024-07-05", loan=loan.name)
		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2024-07-05")[
			"payable_amount"
		]
		create_repayment_entry(loan.name, "2024-07-05", payable_amount).submit()
		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")

		data, _ = self.run_report(loan, disb, "2024-03-01")
		self.assertTrue(data, "Loan should still appear for a date before it was closed")
		self.assertGreater(data[0].get("pending_principal_amount"), 0)

	def test_loan_outstanding_report_overdue_ignores_later_repayment(self):
		loan, disb = self.make_loan_and_disbursement()

		process_daily_loan_demands(posting_date="2024-03-01", loan=loan.name)

		data_overdue, _ = self.run_report(loan, disb, "2024-03-01")
		overdue_before_payment = data_overdue[0].get("principal_overdue")
		self.assertGreater(overdue_before_payment, 0)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2024-06-01")[
			"payable_amount"
		]
		create_repayment_entry(loan.name, "2024-06-01", payable_amount).submit()

		data_after, _ = self.run_report(loan, disb, "2024-03-01")
		self.assertEqual(data_after[0].get("principal_overdue"), overdue_before_payment)

	def test_loan_outstanding_report_uses_disbursed_status_as_on_date(self):
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
			55000,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)

		# Only half the loan is out as of this date: outstanding should be
		# bounded by what was actually disbursed, not the full EMI schedule.
		data, _ = self.run_report(loan, disb, "2024-01-10")
		self.assertLessEqual(data[0].get("pending_principal_amount"), 55000)

		make_loan_disbursement_entry(
			loan.name,
			55000,
			disbursement_date="2024-02-10",
			repayment_start_date="2024-03-05",
		)
		loan.load_from_db()
		self.assertEqual(loan.status, "Disbursed")

		# Loan is now fully Disbursed, but the same earlier as_on_date must
		# still reflect that only the first tranche was out at that time.
		data, _ = self.run_report(loan, disb, "2024-01-10")
		self.assertLessEqual(data[0].get("pending_principal_amount"), 55000)

	def test_loan_outstanding_report_ignores_demand_paid_at_creation(self):
		loan, disb = self.make_loan_and_disbursement()

		# A demand created already fully paid (e.g. interest booked as part of
		# a repayment, with no separate Loan Repayment Detail allocation).
		create_loan_demand(
			loan.name,
			"2024-02-05",
			"Normal",
			"Interest",
			500,
			loan_disbursement=disb.name,
			paid_amount=500,
		)

		data, _ = self.run_report(loan, disb, "2024-02-10")
		self.assertEqual(data[0].get("interest_overdue"), 0)

	def test_loan_outstanding_report_matches_live_calculation_for_today(self):
		loan, disb = self.make_loan_and_disbursement()

		data, _ = self.run_report(loan, disb, nowdate())
		loan.load_from_db()
		self.assertEqual(data[0].get("pending_principal_amount"), get_pending_principal_amount(loan))

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
