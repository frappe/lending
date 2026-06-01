import frappe
from frappe.utils import flt

from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.report.alm_audit_report.alm_audit_report import (
	execute,
	get_ageing_bucket,
	get_ageing_map,
	get_columns,
	get_future_interest_details,
	get_overdue_details,
)
from lending.tests.test_utils import create_loan, make_loan_disbursement_entry
from lending.tests.utils import LendingTestSuite


class TestALMAuditReport(LendingTestSuite):
	# Ageing bucket helpers

	def test_alm_audit_report_gets_ageing_bucket(self):
		bucket = get_ageing_bucket("2024-01-31", "2024-01-31")
		self.assertEqual(bucket, "Overdue")

	def test_alm_audit_report_gets_ageing_bucket_for_various_ranges(self):
		# 15 days ahead → "0-31"
		self.assertEqual(
			get_ageing_bucket("2024-02-15", "2024-01-31"),
			"1 day to 30/31 days (one month)",
		)
		# 45 days → "32-60"
		self.assertEqual(get_ageing_bucket("2024-03-16", "2024-01-31"), "1 to 2 Months")
		# 75 days → "61-90"
		self.assertEqual(
			get_ageing_bucket("2024-04-15", "2024-01-31"), "Over 2 Months upto 3 Months"
		)
		# 122 days → "91-180"
		self.assertEqual(
			get_ageing_bucket("2024-06-01", "2024-01-31"), "Over 3 Months to 6 Months"
		)
		# 201 days → "181-365"
		self.assertEqual(
			get_ageing_bucket("2024-08-19", "2024-01-31"), "Over 6 Months to 1 Year"
		)
		# ~501 days → "365-1095"
		self.assertEqual(get_ageing_bucket("2025-06-15", "2024-01-31"), "1 to 3 Years")

	# Ageing map

	def test_alm_audit_report_returns_expected_ageing_map(self):
		ageing_map = get_ageing_map()
		expected_ageing_map = {
			"0-0": "Overdue",
			"0-31": "1 day to 30/31 days (one month)",
			"32-60": "1 to 2 Months",
			"61-90": "Over 2 Months upto 3 Months",
			"91-180": "Over 3 Months to 6 Months",
			"181-365": "Over 6 Months to 1 Year",
			"365-1095": "1 to 3 Years",
			"1096-1825": "3 to 5 Years",
			"1826-100000": "Over 5 Years",
		}
		self.assertEqual(ageing_map, expected_ageing_map)

	def test_alm_audit_report_defines_columns(self):
		columns = get_columns()
		required_fieldnames = {"loan", "loan_product", "ageing", "accrued_principal", "accrued_interest"}
		self.assertTrue(required_fieldnames.issubset({c.get("fieldname") for c in columns}))

	# get_future_interest_details

	def test_alm_audit_report_get_future_interest_details_returns_bucket_map(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			repayment_start_date="2024-02-05",
			posting_date="2024-01-05",
			rate_of_interest=12,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)

		future_details_map, loans, loan_product_map = get_future_interest_details(
			"2024-01-05", "_Test Company"
		)

		self.assertIn(loan.name, loans)
		self.assertEqual(loan_product_map.get(loan.name), "Term Loan Product 4")
		loan_buckets = future_details_map.get(loan.name)
		self.assertIsNotNone(loan_buckets, "Expected EMI buckets for the created loan")
		self.assertGreater(len(loan_buckets), 0)
		for bucket, details in loan_buckets.items():
			self.assertIn(bucket, get_ageing_map().values())
			self.assertGreaterEqual(flt(details.interest_amount), 0)
			self.assertGreaterEqual(flt(details.principal_amount), 0)

	# get_overdue_details

	def test_alm_audit_report_get_overdue_details_aggregates_principal_and_interest(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			90000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			repayment_start_date="2024-02-05",
			posting_date="2024-01-05",
			rate_of_interest=12,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)
		process_daily_loan_demands("2024-02-05", loan=loan.name)

		overdue_details = get_overdue_details("2024-03-01", "_Test Company")

		self.assertIn(loan.name, overdue_details)
		entry = overdue_details[loan.name]
		self.assertIn("total_pending_principal", entry)
		self.assertIn("total_pending_interest", entry)
		total = entry.get("total_pending_principal", 0) + entry.get("total_pending_interest", 0)
		self.assertGreater(total, 0)

	def test_alm_audit_report_get_overdue_details_aggregates_penalty_demand(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			60000,
			"Repay Over Number of Periods",
			4,
			"Customer",
			repayment_start_date="2024-02-05",
			posting_date="2024-01-05",
			rate_of_interest=12,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)

		# Insert a penalty demand directly (bypassing GL/accrual hooks) to cover
		# the "Penalty"/"Additional Interest" aggregation branch in get_overdue_details.
		penalty_demand = frappe.get_doc(
			{
				"doctype": "Loan Demand",
				"loan": loan.name,
				"company": "_Test Company",
				"loan_product": loan.loan_product,
				"demand_type": "EMI",
				"demand_subtype": "Penalty",
				"demand_date": "2024-02-05 00:00:00",
				"demand_amount": 300,
			}
		)
		penalty_demand.insert(ignore_permissions=True)
		frappe.db.set_value("Loan Demand", penalty_demand.name, "docstatus", 1)

		overdue_details = get_overdue_details("2024-03-01", "_Test Company")

		entry = overdue_details.get(loan.name, {})
		self.assertGreater(entry.get("total_pending_penalty", 0), 0)

	# execute (full report)

	def test_alm_audit_report_execute_returns_rows_for_active_loan(self):
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
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)

		report = execute({"company": "_Test Company", "as_on_date": "2024-01-05"})
		columns, data = report

		required_fieldnames = {"loan", "loan_product", "ageing", "accrued_principal", "accrued_interest"}
		self.assertTrue(required_fieldnames.issubset({c.get("fieldname") for c in columns}))

		loan_rows = [r for r in data if r.get("loan") == loan.name]
		self.assertTrue(loan_rows, "Expected future EMI report rows for the created loan")
		for row in loan_rows:
			self.assertIn(row.get("ageing"), get_ageing_map().values())
			self.assertEqual(row.get("loan_product"), "Term Loan Product 4")
			self.assertGreaterEqual(flt(row.get("total")), 0)

	def test_alm_audit_report_execute_includes_overdue_rows(self):
		loan = create_loan(
			"_Test Loan Customer",
			"Term Loan Product 4",
			80000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			repayment_start_date="2024-02-05",
			posting_date="2024-01-05",
			rate_of_interest=12,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)
		process_daily_loan_demands("2024-02-05", loan=loan.name)

		# as_on_date after demand_date → unpaid demand is overdue
		report = execute({"company": "_Test Company", "as_on_date": "2024-03-01"})
		columns, data = report

		loan_rows = [r for r in data if r.get("loan") == loan.name]
		self.assertTrue(loan_rows, "Expected report rows for the created loan")

		overdue_rows = [r for r in loan_rows if r.get("ageing") == "Overdue"]
		self.assertTrue(overdue_rows, "Expected at least one Overdue row for loan with past demand")
		self.assertGreater(flt(overdue_rows[0].get("total")), 0)
