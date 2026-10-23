# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from collections import Counter

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, date_diff, flt, getdate

from erpnext.selling.doctype.customer.test_customer import get_customer_dict

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_restructure.installment_skip import (
	get_upcoming_installments,
	skip_installments,
)
from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
	create_process_loan_classification,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	loan_classification_ranges,
	make_loan_disbursement_entry,
	set_loan_accrual_frequency,
)
from lending.tests.utils import LendingTestSuite, with_days_past_due_repost


class TestLoanRestructure(LendingTestSuite):
	applicant2 = "_Test Loan Customer"

	@classmethod
	def make_class_data(cls):
		set_loan_accrual_frequency("Weekly")
		loan_classification_ranges()

	def test_loan_restructure_charges_waiver_and_capitalization(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Monthly")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2026-09-28",
			posting_date="2026-08-14",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-08-14", repayment_start_date="2026-09-28"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-09-28")

		frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2026-08-14",
				"value_date": "2026-08-14",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"debit_to": "Processing Fee Receivable Account - _TC",
				"items":
				[
					{"item_code": "Processing Fee", "qty": 1, "rate": 4000},
					{"item_code": "Documentation Charge", "qty": 1, "rate": 3000},
				],
			}
		).submit()

		frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2026-08-14",
				"value_date": "2026-08-14",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 2000}],
			}
		).submit()

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-04",
			interest_waiver_amount=500,
			loan_restructure_charges=[
				{"charge": "Processing Fee", "capitalize_amount": 6000, "treatment_of_other_charges": "Capitalize"},
				{"charge": "Documentation Charge", "capitalize_amount": 2500, "treatment_of_other_charges": "Capitalize"},
				{"charge": "Processing Fee", "restructure_charge_amount": 3000, "is_post_restructure_charge": 1},
				{"charge": "Documentation Charge", "restructure_charge_amount": 1000, "is_post_restructure_charge": 1}
			],
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		repayments = frappe.db.get_all(
			"Loan Repayment",
			filters={"loan_restructure": loan_restructure.name, "docstatus": 1},
			pluck="repayment_type",
		)

		self.assertEqual(len(repayments), 8)

		counts = Counter(repayments)

		self.assertEqual(counts.get("Charges Capitalization", 0), 3)
		self.assertEqual(counts.get("Charges Waiver", 0), 1)

		sales_invoice = frappe.db.get_value(
			"Sales Invoice",
			{
				"loan": loan.name,
				"docstatus": 1,
				"value_date": "2026-10-04",
			},
			["outstanding_amount", "status"],
			as_dict=True,
		)
		self.assertEqual(flt(sales_invoice.outstanding_amount), 0, "Expected the Sales Invoice for post-restructure charges to be fully paid.")
		self.assertEqual(sales_invoice.status, "Paid", "Expected the Sales Invoice for post-restructure charges to have status 'Paid'.")

	def test_unaccrued_interest_capitalization_gl_entries(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Monthly")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2300000,
			"Repay Over Number of Periods",
			24,
			repayment_start_date="2025-11-05",
			posting_date="2025-10-09",
			rate_of_interest=27,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-10-09", repayment_start_date="2025-11-05"
		)

		process_loan_interest_accrual_for_loans(posting_date="2025-12-04", loan=loan.name, company="_Test Company")
		process_daily_loan_demands(loan=loan.name, posting_date="2026-01-05")
		process_loan_interest_accrual_for_loans(posting_date="2026-02-03", loan=loan.name, company="_Test Company")

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-02-04",
			interest_waiver_amount=1001,
			unaccrued_interest_waiver=1004,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan_repayment = frappe.db.get_value(
			"Loan Repayment",
			{
				"loan_restructure": loan_restructure.name,
				"docstatus": 1,
				"repayment_type": "Interest Capitalization",
				"unbooked_interest_paid": (">", 0),
			},
			["name", "unbooked_interest_paid"],
			as_dict=True,
		)

		amount = flt(loan_repayment.unbooked_interest_paid, 2)

		gl_entries = frappe.db.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Loan Repayment",
				"voucher_no": loan_repayment.name,
				"is_cancelled": 0,
			},
			fields=["account", "debit", "credit"],
		)

		expected_entries = [
			{"account": "Loan Account - _TC", "debit": amount, "credit": 0.0},
			{"account": "Interest Receivable - _TC", "debit": 0.0, "credit": amount},
		]

		for expected in expected_entries:
			self.assertIn(expected, gl_entries, f"Missing GL entry: {expected}")

	def test_normal_restructure_first_emi_schedule_days(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Monthly")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			1200000,
			"Repay Over Number of Periods",
			36,
			repayment_start_date="2025-10-05",
			posting_date="2024-09-19",
			rate_of_interest=24,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-09-19", repayment_start_date="2025-10-05"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-01-05")

		restructure_date = "2026-02-02"
		repayment_start_date = "2026-02-05"

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date=restructure_date,
			repayment_start_date=repayment_start_date
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "loan_restructure": loan_restructure.name}
		)

		date_diff_value = date_diff(repayment_start_date, restructure_date)
		number_of_days_for_first_emi = loan_repayment_schedule.repayment_schedule[0].number_of_days

		self.assertEqual(date_diff_value, number_of_days_for_first_emi)

	@with_days_past_due_repost
	def test_non_npa_restructure_resets_dpd_without_watch_period(self):
		"""
		Verify that restructuring a non-NPA loan resets DPD to zero
		without setting any watch period or NPA tagging.
		"""
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2026-05-29",
			posting_date="2026-04-14",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-04-14", repayment_start_date="2026-05-29"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-05-28", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-05-29")
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-06-03")
		create_process_loan_classification(posting_date="2026-06-04", loan=loan.name)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-06-04",
			repayment_start_date="2026-07-04",
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan.load_from_db()
		self.assertFalse(loan.watch_period_end_date)
		self.assertEqual(loan.days_past_due, 0)
		self.assertEqual(loan.is_npa, 0)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-04")
		create_process_loan_classification(posting_date="2026-10-04", loan=loan.name, force_update_dpd_in_loan=1)

		loan.load_from_db()
		self.assertEqual(loan.is_npa, 1)
		watch_period_days = frappe.db.get_value(
			"Company", "_Test Company", "watch_period_post_loan_restructure_in_days"
		)
		watch_period_end_date = add_days("2026-10-04", watch_period_days)

		self.assertEqual(loan.watch_period_end_date, getdate(watch_period_end_date))

	@with_days_past_due_repost
	def test_npa_restructure_keeps_classification_same(self):
		"""
		Verify that after restructuring an NPA loan,
		the loan classification stays the same during the watch period.
		"""

		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		customer = frappe.get_doc(get_customer_dict("NPA Restructure 1")).insert()
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan = create_loan(
			customer.name,
			"Term Loan Product 4",
			2300000.00,
			"Repay Over Number of Periods",
			24,
			repayment_start_date="2026-05-06",
			posting_date="2026-04-14",
			rate_of_interest=27,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-04-14", repayment_start_date="2026-05-06"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-09-06")

		process_loan_interest_accrual_for_loans(
			posting_date="2026-09-19", loan=loan.name, company="_Test Company"
		)

		create_process_loan_classification(posting_date="2026-09-19", loan=loan.name, force_update_dpd_in_loan=1)

		loan.load_from_db()
		classification_code = loan.classification_code

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-09-19",
			repayment_start_date="2026-10-04",
			interest_waiver_amount=1001,
			unaccrued_interest_waiver=1002,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan.load_from_db()
		self.assertTrue(loan.watch_period_end_date)
		self.assertEqual(loan.days_past_due, 0)
		self.assertEqual(loan.is_npa, 1)
		self.assertEqual(loan.classification_code, classification_code)

	def test_normal_restructure_repayment_schedule_matches_new_tenure(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		frappe.db.set_value("Loan Product", "Term Loan Product 4", "emi_rounding_method", "Round to Nearest")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			130,
			"Repay Over Number of Periods",
			3,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=10,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2026-09-01",
			repayment_start_date="2026-10-07",
			repayment_frequency="Monthly",
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-09-07")

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-09-17",
			repayment_start_date="2026-10-07",
			treatment_of_normal_interest="Add To First EMI",
			unaccrued_interest_treatment="Add To First EMI",
			treatment_of_penal_interest="Capitalize",
			new_rate_of_interest=20,
			new_repayment_method="Repay Over Number of Periods",
			new_repayment_period_in_months=12,
			waive_off_restructure_charges=1,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		new_schedule = frappe.get_doc(
			"Loan Repayment Schedule",
			{"loan_restructure": loan_restructure.name, "docstatus": 1, "status": "Active"},
		)

		self.assertEqual(
			len(new_schedule.repayment_schedule), loan_restructure.new_repayment_period_in_months
		)
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)

	def test_restructure_of_one_time_loan_uses_new_tenure(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			1000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2026-10-24",
			posting_date="2026-09-24",
			rate_of_interest=20,
			applicant_type="Customer",
			repayment_frequency="One Time",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2026-09-24",
			repayment_start_date="2026-10-24",
			repayment_frequency="One Time",
		)

		schedule_before = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)
		self.assertEqual(schedule_before.repayment_frequency, "One Time")
		self.assertEqual(len(schedule_before.repayment_schedule), 1)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-09-28",
			repayment_start_date="2026-09-30",
			treatment_of_normal_interest="Add To First EMI",
			unaccrued_interest_treatment="Add To First EMI",
			treatment_of_penal_interest="Capitalize",
			new_rate_of_interest=20,
			new_repayment_method="Repay Over Number of Periods",
			new_repayment_period_in_months=12,
			waive_off_restructure_charges=1,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		new_schedule = frappe.get_doc(
			"Loan Repayment Schedule",
			{"loan_restructure": loan_restructure.name, "docstatus": 1, "status": "Active"},
		)

		self.assertEqual(new_schedule.repayment_frequency, "Monthly")
		self.assertEqual(
			len(new_schedule.repayment_schedule), loan_restructure.new_repayment_period_in_months
		)

		loan.reload()
		self.assertEqual(loan.repayment_frequency, "Monthly")

		loan_restructure.cancel()

		loan.reload()
		self.assertEqual(loan.repayment_frequency, "One Time")

	@with_days_past_due_repost
	def test_npa_restructure_watch_period_resets_on_dpd(self):
		"""
		Verify that when DPD increases after NPA restructuring,
		the watch period is reset from the new DPD date.
		"""

		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		customer = frappe.get_doc(get_customer_dict("NPA Restructure 1")).insert()
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan = create_loan(
			customer.name,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2026-03-05",
			posting_date="2026-01-20",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-01-20", repayment_start_date="2026-03-05"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-07-05")

		create_process_loan_classification(posting_date="2026-07-05", loan=loan.name, force_update_dpd_in_loan=1)

		loan.load_from_db()
		classification_code = loan.classification_code

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-07-06",
			repayment_start_date="2026-08-05",
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan.load_from_db()
		self.assertTrue(loan.watch_period_end_date)
		self.assertEqual(loan.days_past_due, 0)
		self.assertEqual(loan.is_npa, 1)
		self.assertEqual(loan.classification_code, classification_code)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-08-05")
		amounts = calculate_amounts(against_loan=loan.name, posting_date="2026-08-05")
		payable_amount = round(float(amounts["payable_amount"] or 0.0), 2)

		repayment_entry = create_repayment_entry(loan.name, "2026-08-05", payable_amount)
		repayment_entry.submit()

		process_daily_loan_demands(loan=loan.name, posting_date="2026-09-05")
		amounts = calculate_amounts(against_loan=loan.name, posting_date="2026-09-05")
		payable_amount = round(float(amounts["payable_amount"] or 0.0), 2)

		repayment_entry = create_repayment_entry(loan.name, "2026-09-05", payable_amount)
		repayment_entry.submit()

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-05")
		create_process_loan_classification(posting_date="2026-10-05", loan=loan.name, force_update_dpd_in_loan=1)
		loan.load_from_db()
		watch_period_days = frappe.db.get_value(
			"Company", "_Test Company", "watch_period_post_loan_restructure_in_days"
		)
		watch_period_end_date = add_days("2026-10-05", watch_period_days)

		self.assertEqual(loan.watch_period_end_date, getdate(watch_period_end_date))


class TestInstallmentSkip(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()

	def test_installment_skip_rebuilds_repayment_schedule(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		old_schedule = get_active_schedule(loan.name)
		pending_principal = old_schedule.repayment_schedule[2].balance_loan_amount + old_schedule.repayment_schedule[2].principal_amount

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07"],
		)
		self.assertEqual(loan_restructure.status, "Initiated")

		loan_restructure.status = "Approved"
		loan_restructure.save()

		new_schedule = get_active_schedule(loan.name)
		first_row = get_row(new_schedule, "2026-11-07")

		self.assertEqual(frappe.db.get_value("Loan Repayment Schedule", old_schedule.name, "status"), "Rescheduled")
		self.assertEqual(getdate(first_row.payment_date), getdate("2026-11-07"))
		self.assertEqual((first_row.principal_amount, first_row.interest_amount, first_row.total_payment), (0, 0, 0))
		self.assertEqual(first_row.demand_generated, 1)

		# Same EMI, so the maturity moves by one period
		self.assertEqual(new_schedule.monthly_repayment_amount, old_schedule.monthly_repayment_amount)
		self.assertEqual(len(new_schedule.repayment_schedule), len(old_schedule.repayment_schedule) + 1)
		self.assertEqual(getdate(new_schedule.repayment_schedule[-1].payment_date), getdate("2027-04-07"))

		# Principal is fully repaid and the skipped interest is added to the next installment demand
		rebuilt_rows = [row for row in new_schedule.repayment_schedule if getdate(row.payment_date) >= getdate("2026-11-07")]
		self.assertEqual(flt(sum(row.principal_amount for row in rebuilt_rows), 2), flt(pending_principal, 2))

		# Like a Pre Payment schedule, it keeps every earlier row and the loan's own start date
		self.assertEqual(new_schedule.repayment_start_date, old_schedule.repayment_start_date)
		self.assertEqual(
			[(row.payment_date, row.demand_generated) for row in new_schedule.repayment_schedule[:2]],
			[(row.payment_date, row.demand_generated) for row in old_schedule.repayment_schedule[:2]],
		)
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)
		# Interest of Oct 7 to Dec 7 (daily accruals add a few paise of rounding)
		self.assertAlmostEqual(
			next_row(new_schedule, "2026-11-07").interest_amount,
			first_row.balance_loan_amount * 12 * 61 / 36500,
			delta=0.5,
		)

	def test_skipped_installment_is_not_demanded_or_overdue(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07"],
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-20")

		self.assertEqual(get_demand_dates(loan.name).count(getdate("2026-11-07")), 0)
		self.assertEqual(calculate_amounts(loan.name, "2026-11-20")["payable_amount"], 0)

		loan.load_from_db()
		self.assertEqual(loan.days_past_due, 0)

		# Next installment demand is raised once, with the skipped interest
		process_daily_loan_demands(loan=loan.name, posting_date="2026-12-07")
		new_schedule = get_active_schedule(loan.name)

		self.assertEqual(get_demand_dates(loan.name).count(getdate("2026-12-07")), 2)
		self.assertEqual(
			calculate_amounts(loan.name, "2026-12-07")["payable_amount"],
			next_row(new_schedule, "2026-11-07").total_payment,
		)

	def test_installment_skip_with_multiple_installments(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		old_schedule = get_active_schedule(loan.name)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07", "2027-01-07"],
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		new_schedule = get_active_schedule(loan.name)
		skipped_rows = [row for row in new_schedule.repayment_schedule if not row.total_payment]

		self.assertEqual(
			[getdate(row.payment_date) for row in skipped_rows], [getdate("2026-11-07"), getdate("2027-01-07")]
		)
		self.assertTrue(all(row.demand_generated for row in skipped_rows))
		self.assertEqual(len(new_schedule.repayment_schedule), len(old_schedule.repayment_schedule) + 2)
		self.assertEqual(getdate(new_schedule.repayment_schedule[-1].payment_date), getdate("2027-05-07"))
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)

	def test_installment_skip_keeps_maturity_when_repaying_over_periods(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		old_schedule = get_active_schedule(loan.name)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07"],
			new_repayment_method="Repay Over Number of Periods",
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		new_schedule = get_active_schedule(loan.name)

		self.assertEqual(new_schedule.repayment_schedule[-1].payment_date, old_schedule.repayment_schedule[-1].payment_date)
		self.assertGreater(new_schedule.monthly_repayment_amount, old_schedule.monthly_repayment_amount)
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)

	def test_skipping_last_installment_extends_maturity(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2027-03-07"],
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		new_schedule = get_active_schedule(loan.name)

		self.assertEqual(getdate(new_schedule.repayment_schedule[-1].payment_date), getdate("2027-04-07"))
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)

	def test_rejected_installment_skip_keeps_original_schedule(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		old_schedule = get_active_schedule(loan.name)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07"],
		)
		loan_restructure.status = "Rejected"
		loan_restructure.save()

		self.assertEqual(get_active_schedule(loan.name).name, old_schedule.name)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-10")
		self.assertIn(getdate("2026-11-07"), get_demand_dates(loan.name))

		# A new request is allowed after a rejection
		create_repayment_entry(
			loan.name, "2026-11-10", calculate_amounts(loan.name, "2026-11-10")["payable_amount"]
		).submit()
		create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-11-12",
			restructure_type="Installment Skip",
			skipped_dates=["2026-12-07"],
		)

	def test_cancelling_approved_installment_skip_restores_schedule(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		old_schedule = get_active_schedule(loan.name)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07"],
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan_restructure.reload()
		loan_restructure.cancel()

		restored_schedule = get_active_schedule(loan.name)
		self.assertEqual(restored_schedule.name, old_schedule.name)
		self.assertEqual(restored_schedule.repayment_schedule[2].demand_generated, 0)

	def test_invalid_installment_skip_requests(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		invalid_requests = [
			# not a schedule date
			("2026-10-20", ["2026-11-08"], None),
			# installment with demand already generated
			("2026-10-20", ["2026-10-07"], None),
			# same installment twice
			("2026-10-20", ["2026-11-07", "2026-11-07"], None),
			# nothing selected
			("2026-10-20", [], None),
			# installment is before the restructure date
			("2026-11-10", ["2026-11-07"], None),
			# no installment left to repay
			(
				"2026-10-20",
				["2026-11-07", "2026-12-07", "2027-01-07", "2027-02-07", "2027-03-07"],
				"Repay Over Number of Periods",
			),
		]

		for restructure_date, skipped_dates, new_repayment_method in invalid_requests:
			with self.assertRaises(frappe.ValidationError):
				create_loan_restructure(
					loan=loan.name,
					restructure_date=restructure_date,
					restructure_type="Installment Skip",
					skipped_dates=skipped_dates,
					new_repayment_method=new_repayment_method,
				)

	def test_duplicate_installment_skip_requests(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07"],
		)

		# Second request while the first is pending
		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-10-21",
				restructure_type="Installment Skip",
				skipped_dates=["2026-12-07"],
			)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		# The same installment cannot be skipped twice
		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-10-21",
				restructure_type="Installment Skip",
				skipped_dates=["2026-11-07"],
			)

		# Another installment can be skipped once the first request is done
		second_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-21",
			restructure_type="Installment Skip",
			skipped_dates=["2026-12-07"],
		)
		second_restructure.status = "Approved"
		second_restructure.save()

		new_schedule = get_active_schedule(loan.name)
		# The first skip stays in force when another one is added
		skipped_dates = [getdate(row.payment_date) for row in new_schedule.repayment_schedule if not row.total_payment]
		self.assertEqual(skipped_dates, [getdate("2026-11-07"), getdate("2026-12-07")])

	def test_skip_installments_creates_and_approves_restructure(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		open_installments = get_upcoming_installments(loan.name)
		self.assertEqual(getdate(open_installments[0]["payment_date"]), getdate("2026-11-07"))

		restructure = skip_installments(
			loan.name, '["2026-11-07"]', reason="Employee request", approve=0, restructure_date="2026-10-20"
		)
		restructure = frappe.get_doc("Loan Restructure", restructure)
		self.assertEqual((restructure.restructure_type, restructure.status), ("Installment Skip", "Initiated"))
		self.assertEqual(restructure.reason_for_restructure, "Employee request")

		restructure.status = "Rejected"
		restructure.save()

		restructure = frappe.get_doc("Loan Restructure", skip_installments(loan.name, '["2026-11-07"]', restructure_date="2026-10-20"))
		self.assertEqual(restructure.status, "Approved")
		self.assertEqual(get_row(get_active_schedule(loan.name), "2026-11-07").demand_generated, 1)

	def make_loan_with_first_emi_paid(self, method="Repay Over Number of Periods"):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			method,
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)
		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		return loan

	def test_loan_manager_can_skip_installments(self):
		loan = self.make_loan_with_first_emi_paid()

		email = "loan.manager.skip@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Loan Manager", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		user.add_roles("Loan Manager")

		frappe.set_user(email)
		try:
			name = skip_installments(loan.name, '["2026-11-07"]', restructure_date="2026-10-20")
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Loan Restructure", name, "status"), "Approved")

	def test_skipping_last_installment_keeps_end_date(self):
		loan = self.make_loan_with_first_emi_paid()

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(
				loan.name,
				'["2027-03-07"]',
				new_repayment_method="Repay Over Number of Periods",
				restructure_date="2026-10-20",
			),
		)
		self.assertEqual(restructure.status, "Approved")

		# The skipped date is at the end of the term, so the last payable row is the one before it
		rows = get_active_schedule(loan.name).repayment_schedule
		self.assertEqual(getdate(rows[-1].payment_date), getdate("2027-02-07"))
		self.assertEqual(flt(rows[-1].balance_loan_amount, 2), 0)
		self.assertEqual(rows[-1].demand_generated, 0)
		self.assertTrue(all(getdate(row.payment_date) <= getdate("2027-02-07") for row in rows))

	def test_later_skip_remembers_skipped_date_at_end_of_term(self):
		loan = self.make_loan_with_first_emi_paid()

		skip_installments(
			loan.name,
			'["2027-03-07"]',
			new_repayment_method="Repay Over Number of Periods",
			restructure_date="2026-10-20",
		)
		skip_installments(loan.name, '["2026-11-07"]', restructure_date="2026-10-21")

		schedule = get_active_schedule(loan.name)
		self.assertEqual(get_row(schedule, "2026-11-07").total_payment, 0)
		self.assertFalse(any(getdate(row.payment_date) == getdate("2027-03-07") and row.total_payment for row in schedule.repayment_schedule))
		self.assertEqual(flt(schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)

	def test_installment_skip_updates_loan_and_cancel_restores_it(self):
		loan = self.make_loan_with_first_emi_paid()
		old_emi, old_periods = frappe.db.get_value("Loan", loan.name, ["monthly_repayment_amount", "repayment_periods"])

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(loan.name, '["2026-11-07"]', restructure_date="2026-10-20"),
		)

		new_emi, new_periods = frappe.db.get_value("Loan", loan.name, ["monthly_repayment_amount", "repayment_periods"])
		self.assertEqual(new_emi, get_active_schedule(loan.name).monthly_repayment_amount)
		self.assertEqual(new_periods, old_periods + 1)

		restructure.cancel()
		emi, periods = frappe.db.get_value("Loan", loan.name, ["monthly_repayment_amount", "repayment_periods"])
		self.assertEqual((emi, periods), (old_emi, old_periods))

	def test_installment_skip_is_not_allowed_for_partially_disbursed_loan(self):
		loan = self.make_loan_with_first_emi_paid()
		frappe.db.set_value("Loan", loan.name, "status", "Partially Disbursed")

		self.assertRaises(
			frappe.ValidationError,
			skip_installments,
			loan.name,
			'["2026-11-07"]',
			restructure_date="2026-10-20",
		)

	def test_installment_skip_starts_after_last_accrual(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		# Interest is already accrued till Nov 8, e.g. by a payroll run for a later period
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")
		create_repayment_entry(
			loan.name, "2026-11-07", calculate_amounts(loan.name, "2026-11-07")["payable_amount"]
		).submit()
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-11-08")

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(loan.name, '["2026-12-07"]', restructure_date="2026-10-20"),
		)

		self.assertEqual(restructure.status, "Approved")
		self.assertGreaterEqual(getdate(restructure.restructure_date), getdate("2026-11-08"))

	def test_installment_skip_does_not_demand_interest_twice(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		# Interest is accrued till Nov 6 and the Nov 7 installment is demanded and paid
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-11-06")
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")
		create_repayment_entry(
			loan.name, "2026-11-07", calculate_amounts(loan.name, "2026-11-07")["payable_amount"]
		).submit()

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(loan.name, '["2026-12-07"]', restructure_date="2026-10-20"),
		)
		new_schedule = get_active_schedule(loan.name)

		# Starts at the demanded installment, so nothing before it is added again
		self.assertEqual(getdate(restructure.restructure_date), getdate("2026-11-07"))
		self.assertEqual(restructure.unaccrued_interest, 0)

		# Interest of Nov 7 to Jan 7 is demanded once: skipped Dec 7 and the Jan 7 installment
		self.assertAlmostEqual(
			next_row(new_schedule, "2026-12-07").interest_amount,
			restructure.new_loan_amount * 12 * 61 / 36500,
			delta=0.5,
		)

		# Entered directly, an earlier date is refused
		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-11-06",
				restructure_type="Installment Skip",
				skipped_dates=["2027-01-07"],
			)

	def test_installment_skip_generates_demand_for_due_installments_first(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-25",
			posting_date="2026-09-15",
			rate_of_interest=12,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-15", repayment_start_date="2026-10-25"
		)

		# No demand is generated yet, so the broken period interest row of 25 Sep is still open
		self.assertEqual(get_demand_dates(loan.name), [])
		offered = [getdate(row["payment_date"]) for row in get_upcoming_installments(loan.name)]
		self.assertTrue(offered)
		self.assertGreaterEqual(min(offered), getdate("2026-10-25"))

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(loan.name, '["2026-11-25"]', restructure_date="2026-10-23"),
		)

		self.assertEqual(restructure.status, "Approved")
		self.assertIn(getdate("2026-09-25"), get_demand_dates(loan.name))
		new_schedule = get_active_schedule(loan.name)
		self.assertEqual(get_row(new_schedule, "2026-09-25").demand_generated, 1)
		self.assertEqual(getdate(next_row(new_schedule, "2026-09-25").payment_date), getdate("2026-10-25"))

		# Entered directly, with an installment still rows_without_demand before the date, it is refused
		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-11-30",
				restructure_type="Installment Skip",
				skipped_dates=["2026-12-25"],
			)

	def test_later_installment_skip_keeps_earlier_skip(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		skip_installments(loan.name, '["2027-01-07"]', restructure_date="2026-10-20")
		skip_installments(loan.name, '["2026-12-07"]', restructure_date="2026-10-21")
		new_schedule = get_active_schedule(loan.name)

		# The schedule still starts on the loan's own repayment start date after two skips
		self.assertEqual(new_schedule.repayment_start_date, getdate("2026-10-07"))

		# Both skips are in force, and a third installment was added at the end for each
		skipped_rows = [row for row in new_schedule.repayment_schedule if not row.total_payment]
		self.assertEqual(
			[getdate(row.payment_date) for row in skipped_rows], [getdate("2026-12-07"), getdate("2027-01-07")]
		)
		self.assertTrue(all(row.demand_generated for row in skipped_rows))
		self.assertEqual(getdate(new_schedule.repayment_schedule[-1].payment_date), getdate("2027-05-07"))
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)

		# Neither skipped installment gets a demand
		process_daily_loan_demands(loan=loan.name, posting_date="2027-01-10")
		self.assertNotIn(getdate("2026-12-07"), get_demand_dates(loan.name))
		self.assertNotIn(getdate("2027-01-07"), get_demand_dates(loan.name))

	def test_installment_skip_is_not_allowed_with_overdue(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")

		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-11-10",
				restructure_type="Installment Skip",
				skipped_dates=["2026-12-07"],
			)

	def test_repayment_without_installment_skip_is_unchanged(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-07",
			posting_date="2026-09-01",
			rate_of_interest=12,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-10-06", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
		create_repayment_entry(
			loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
		).submit()

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

		old_schedule = get_active_schedule(loan.name)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")

		self.assertEqual(get_active_schedule(loan.name).name, old_schedule.name)
		self.assertEqual(
			calculate_amounts(loan.name, "2026-11-07")["payable_amount"],
			old_schedule.repayment_schedule[2].total_payment,
		)



def create_loan_restructure(
	loan,
	restructure_date,
	repayment_start_date=None,
	interest_waiver_amount=None,
	unaccrued_interest_waiver=None,
	penal_waiver_amount=None,
	restructure_charge_amount=None,
	is_post_restructure_charge=0,
	treatment_of_normal_interest="Capitalize",
	unaccrued_interest_treatment="Capitalize",
	treatment_of_penal_interest="Capitalize",
	loan_restructure_charges=None,
	new_rate_of_interest=None,
	new_repayment_method=None,
	new_repayment_period_in_months=None,
	waive_off_restructure_charges=0,
	restructure_type="Normal Restructure",
	skipped_dates=None,
	submit=True,
):

	doc = frappe.new_doc("Loan Restructure")
	doc.loan = loan
	doc.restructure_date = restructure_date
	doc.repayment_start_date = repayment_start_date or restructure_date
	doc.interest_waiver_amount = interest_waiver_amount
	doc.unaccrued_interest_waiver = unaccrued_interest_waiver
	doc.penal_interest_waiver = penal_waiver_amount
	doc.restructure_type = restructure_type
	doc.treatment_of_normal_interest = treatment_of_normal_interest
	doc.unaccrued_interest_treatment = unaccrued_interest_treatment
	doc.treatment_of_penal_interest = treatment_of_penal_interest
	doc.new_rate_of_interest = new_rate_of_interest
	doc.new_repayment_method = new_repayment_method
	doc.new_repayment_period_in_months = new_repayment_period_in_months
	doc.waive_off_restructure_charges = waive_off_restructure_charges

	if loan_restructure_charges:
		for charge in loan_restructure_charges:
			doc.append(
				"loan_restructure_charges",
				{
					"charge": charge.get("charge"),
					"is_post_restructure_charge": charge.get("is_post_restructure_charge", 0),
					"restructure_charge_amount": charge.get("restructure_charge_amount"),
					"capitalize_amount": charge.get("capitalize_amount"),
					"treatment_of_other_charges": charge.get("treatment_of_other_charges"),
				},
			)

	for date in skipped_dates or []:
		doc.append("skipped_installments", {"payment_date": date})

	if submit:
		doc.submit()
	else:
		doc.insert()

	return doc


class TestOverdueLoanRestructure(LendingTestSuite):
	@classmethod
	def make_class_data(cls):
		loan_classification_ranges()
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2026-09-28",
			posting_date="2026-08-14",
			rate_of_interest=8.5,
			applicant_type="Customer",
			penalty_charges_rate=36,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-08-14", repayment_start_date="2026-09-28"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2026-09-27", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-09-28")

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-03")
		cls.loan = loan.name

	def test_loan_restructure_capitalization(self):
		loan = frappe.get_doc("Loan", self.loan)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2026-08-14",
				"value_date": "2026-08-14",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 5000}],
				"debit_to": "Processing Fee Receivable Account - _TC",
			}
		)
		sales_invoice.submit()

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2026-08-14",
				"value_date": "2026-08-14",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Documentation Charge", "qty": 1, "rate": 1000}],
			}
		)
		sales_invoice.submit()

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-04",
			interest_waiver_amount=500,
			penal_waiver_amount=10,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		repayments = frappe.db.get_all(
			"Loan Repayment",
			filters={"loan_restructure": loan_restructure.name, "docstatus": 1},
			pluck="name",
		)

		self.assertEqual(len(repayments), 8)

	def test_clears_principal_overdue_demands_on_normal_restructure(self):
		loan = frappe.get_doc("Loan", self.loan)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-04",
			interest_waiver_amount=500,
			penal_waiver_amount=10,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		LoanDemand = DocType("Loan Demand")

		total_outstanding = (
			frappe.qb.from_(LoanDemand)
			.select(Sum(LoanDemand.outstanding_amount))
			.where(LoanDemand.loan == loan.name)
			.where(LoanDemand.demand_type == "EMI")
			.where(LoanDemand.demand_subtype == "Principal")
			.where(LoanDemand.docstatus == 1)
		).run()[0][0]

		self.assertEqual(flt(total_outstanding), 0)


def get_active_schedule(loan):
	return frappe.get_doc("Loan Repayment Schedule", {"loan": loan, "docstatus": 1, "status": "Active"})


def get_row(schedule, date):
	return next(row for row in schedule.repayment_schedule if getdate(row.payment_date) == getdate(date))


def next_row(schedule, date):
	rows = schedule.repayment_schedule
	return rows[rows.index(get_row(schedule, date)) + 1]


def get_demand_dates(loan):
	return [
		getdate(date) for date in frappe.get_all("Loan Demand", {"loan": loan, "docstatus": 1}, pluck="demand_date")
	]
