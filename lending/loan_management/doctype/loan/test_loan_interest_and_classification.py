# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe
from frappe.utils import add_days, flt, get_datetime, getdate, nowdate

from erpnext.selling.doctype.customer.test_customer import get_customer_dict

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
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
	add_or_update_loan_charges,
	create_loan,
	create_loan_accounts,
	create_loan_product,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_write_off,
	create_repayment_entry,
	get_loan_interest_accrual,
	loan_classification_ranges,
	make_loan_disbursement_entry,
	set_loan_accrual_frequency,
	set_loan_settings_in_company,
	setup_loan_demand_offset_order,
)
from lending.tests.utils import LendingTestSuite


class TestLoanInterestAndClassification(LendingTestSuite):
	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		loan_classification_ranges()

		set_loan_accrual_frequency("Monthly")
		simple_terms_loans = [
			["Personal Loan", 500000, 8.4, "Monthly as per repayment start date"],
			["Term Loan Product 1", 12000, 7.5, "Monthly as per repayment start date"],
		]

		pro_rated_term_loans = [
			["Term Loan Product 2", 12000, 7.5, "Pro-rated calendar months", "Start of the next month"],
			["Term Loan Product 3", 1200, 25, "Pro-rated calendar months", "End of the current month"],
		]

		cyclic_date_term_loans = [
			["Term Loan Product 4", 3000000, 25, "Monthly as per cycle date"],
		]

		loc_loans = [
			["Term Loan Product 5", 3000000, 25, "Line of Credit"],
		]

		flat_interest_rate_loans = [
			["Flat Interest Rate Loan", 1000000, 12, "Flat Interest Rate"],
		]

		for loan_product in simple_terms_loans + flat_interest_rate_loans + loc_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)

		for loan_product in cyclic_date_term_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)
			add_or_update_loan_charges(loan_product[0])

		for loan_product in pro_rated_term_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
				repayment_date_on=loan_product[4],
			)

		create_loan_product(
			"Stock Loan",
			"Stock Loan",
			2000000,
			13.5,
			25,
			1,
			5,
			repayment_schedule_type="Monthly as per repayment start date",
			collection_offset_sequence_for_standard_asset="Test EMI Based Standard Loan Demand Offset Order",
		)

		create_loan_product(
			"Demand Loan",
			"Demand Loan",
			2000000,
			13.5,
			25,
			0,
			5,
			collection_offset_sequence_for_standard_asset="Test Demand Loan Loan Demand Offset Order",
			collection_offset_sequence_for_sub_standard_asset=None,
			collection_offset_sequence_for_written_off_asset=None,
			collection_offset_sequence_for_settlement_collection=None,
		)

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
		create_loan_security_price("Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)

		if not frappe.db.exists("Customer", "_Test Loan Customer"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer")).insert(ignore_permissions=True)

		if not frappe.db.exists("Customer", "_Test Loan Customer 1"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer 1")).insert(ignore_permissions=True)

		if not frappe.db.exists("Customer", "_Test Loan Customer 2"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer 2")).insert(ignore_permissions=True)

		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		self.applicant3 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer 1"}, "name")
		self.applicant1 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer 2"}, "name")

		frappe.db.set_value(
			"Loan Product", "Demand Loan", "customer_refund_account", "Customer Refund Account - _TC"
		)

	def test_interest_accrual_stop_after_freeze_loan(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			posting_date="2025-01-01",
			rate_of_interest=12,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2025-01-01",
			repayment_start_date="2025-01-05",
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2025-02-05", loan=loan.name, company="_Test Company"
		)

		loan.load_from_db()
		loan.freeze_account = 1
		loan.freeze_date = "2025-01-25"
		loan.save()

		process_loan_interest_accrual_for_loans(
			posting_date="2025-02-05", loan=loan.name, company="_Test Company"
		)

		last_accrual_date = frappe.db.get_value(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 1},
			"posting_date",
			order_by="posting_date desc",
		)

		freeze_date = loan.freeze_date
		self.assertEqual(getdate(last_accrual_date), getdate(freeze_date))

	def test_same_date_for_daily_accruals(self):
		from lending.tests.test_utils import get_penalty_amount

		set_loan_accrual_frequency("Daily")
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-01",
			penalty_charges_rate=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-04-01", repayment_start_date="2024-05-05"
		)
		process_daily_loan_demands(posting_date="2024-07-07", loan=loan.name)
		process_loan_interest_accrual_for_loans(
			posting_date="2024-07-06", loan=loan.name, company="_Test Company"
		)

		# Calculate expected penal amount
		expected_penalty_amount = 0

		repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "status": "Active", "docstatus": 1}
		)

		for amount in frappe.db.get_all(
			"Repayment Schedule",
			{"parent": repayment_schedule, "principal_amount": (">", 0), "demand_generated": 1},
			["payment_date", "total_payment"],
		):

			expected_penalty_amount += get_penalty_amount(
				"2024-07-07", amount.payment_date, amount.total_payment, 25
			)

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-07-07")

		self.assertEqual(flt(amounts["penalty_amount"], 2), expected_penalty_amount)

		accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "accrual_type": "Normal Interest"},
			["start_date", "posting_date"],
		)
		for i in accruals:
			self.assertEqual(i.start_date, i.posting_date)

	def test_interest_accrual_and_demand_on_freeze_and_unfreeze(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		loan.load_from_db()
		loan.freeze_account = 1
		loan.freeze_date = "2024-11-10"
		loan.save()

		loan.freeze_account = 0
		loan.save()

	def test_interest_accrual_overlap(self):
		for frequency in ["Monthly", "Weekly", "Daily"]:
			set_loan_accrual_frequency(frequency)
			loan = create_loan(
				self.applicant1,
				"Term Loan Product 4",
				1500000,
				"Repay Over Number of Periods",
				30,
				repayment_start_date="2025-01-05",
				posting_date="2024-11-28",
				rate_of_interest=28,
			)

			loan.submit()

			make_loan_disbursement_entry(
				loan.name, loan.loan_amount, disbursement_date="2024-11-28", repayment_start_date="2025-01-05"
			)

			# Process Loan Interest Accrual
			process_loan_interest_accrual_for_loans(
				posting_date="2024-12-03", loan=loan.name, company="_Test Company"
			)
			process_loan_interest_accrual_for_loans(
				posting_date="2024-12-04", loan=loan.name, company="_Test Company"
			)
			process_loan_interest_accrual_for_loans(
				posting_date="2024-12-05", loan=loan.name, company="_Test Company"
			)

			process_daily_loan_demands(posting_date="2024-12-05", loan=loan.name)

			repayment = create_repayment_entry(loan.name, "2024-12-05", 1150, repayment_type="Pre Payment")

			repayment.submit()
			process_loan_interest_accrual_for_loans(
				posting_date="2024-12-08", loan=loan.name, company="_Test Company"
			)

			process_daily_loan_demands(posting_date="2025-01-05", loan=loan.name)
			process_loan_interest_accrual_for_loans(
				posting_date="2025-01-10", loan=loan.name, company="_Test Company"
			)

			repayment = create_repayment_entry(loan.name, "2025-01-03", 10000, repayment_type="Pre Payment")

			repayment.submit()

	def test_broken_period_interest_for_amortized_over_tenure(self):
		# Broken Period Interest (BPI) Calculation:
		# Disbursement Date = 2023-11-03
		# Loan Product setting "Minimum days between Disbursement date and first Repayment date" = 15
		# With monthly frequency, expected first due date = 2023-12-03
		# Repayment Start Date (explicit) = 2023-12-05
		# Difference = 2 days → Broken Period Days = 2
		#
		# Principal = 100,000
		# Annual Rate = 14.5%
		# Repayment Periods = 12 months
		#
		# BPI = (Principal × Rate × Days) / (365 × 100) = (100000 × 14.5 × 2) / 36500 = 79.45
		#
		# Amortize BPI over 12 periods → 79.45 / 12 = 6.62 per period
		#
		# First Period Interest (Dec 05, 2023)
		# Normal 30-day interest = (100000 × 14.5 × 30) / 36500 = 1191.78
		# Add BPI amount (6.62) → 1191.78 + 6.62 = 1198.40
		#
		# Second Period Interest
		# Normal interest reduces slightly after principal repayment (≈ 1135.31)
		# Add BPI amount (6.62) → 1135.31 + 6.62 = 1141.93

		frappe.db.set_value(
			"Loan Product", "Term Loan Product 4", "bpi_recovery_method", "Amortized Over Tenure"
		)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			posting_date="2023-11-03",
			rate_of_interest=14.5,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2023-11-03", repayment_start_date="2023-12-05"
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1}
		)

		calculated_bpi_amount_1 = flt(loan_repayment_schedule.repayment_schedule[0].interest_amount, 2)
		calculated_bpi_amount_2 = flt(loan_repayment_schedule.repayment_schedule[1].interest_amount, 2)

		self.assertEqual(calculated_bpi_amount_1, 1198.40)
		self.assertEqual(calculated_bpi_amount_2, 1141.93)

	def test_broken_period_interest_for_amortized_over_tenure_for_fixed_amount(self):
		frappe.db.set_value(
			"Loan Product", "Term Loan Product 4", "bpi_recovery_method", "Amortized Over Tenure"
		)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Fixed Amount per Period",
			"Customer",
			monthly_repayment_amount=9003,
			posting_date="2023-11-03",
			rate_of_interest=14.5,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2023-11-03", repayment_start_date="2023-12-05"
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1}
		)

		calculated_bpi_amount_1 = flt(loan_repayment_schedule.repayment_schedule[0].interest_amount, 2)
		calculated_bpi_amount_2 = flt(loan_repayment_schedule.repayment_schedule[1].interest_amount, 2)

		self.assertEqual(calculated_bpi_amount_1, 1198.40)
		self.assertEqual(calculated_bpi_amount_2, 1141.93)

	def test_broken_period_interest_for_add_to_first_emi(self):
		# BPI = (Principal × Rate × Days) / (365 × 100) = (100000 × 14.5 × 2) / 36500 = 79.45
		#
		# Since the BPI recovery method is "Add to First EMI",
		# the full BPI amount is added to the interest of the first repayment period.
		#
		# First Period Interest (Dec 05, 2023)
		# Normal 30-day interest = (100000 × 14.5 × 30) / 36500 = 1191.78
		# Add full BPI (79.45) → 1191.78 + 79.45 ≈ 1271.23

		frappe.db.set_value(
			"Loan Product", "Term Loan Product 4", "bpi_recovery_method", "Add to First EMI"
		)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			posting_date="2023-11-03",
			rate_of_interest=14.5,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2023-11-03", repayment_start_date="2023-12-05"
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1}
		)

		calculated_bpi_amount = flt(loan_repayment_schedule.repayment_schedule[0].interest_amount, 2)
		self.assertEqual(calculated_bpi_amount, 1271.23)

	def test_broken_period_interest_for_upfront_deduction(self):
		# BPI = (Principal × Rate × Days) / (365 × 100) = (100000 × 14.5 × 2) / 36500 = 79.45
		#
		# Since the BPI recovery method is "Upfront Deduction",
		# the full BPI amount is deducted upfront from the disbursed amount.
		# This means the first repayment only contains the BPI amount.
		#
		# First Period Interest = 79.45

		frappe.db.set_value(
			"Loan Product", "Term Loan Product 4", "bpi_recovery_method", "Upfront Deduction"
		)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			posting_date="2023-11-03",
			rate_of_interest=14.5,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2023-11-03", repayment_start_date="2023-12-05"
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1}
		)

		calculated_bpi_amount = flt(loan_repayment_schedule.repayment_schedule[0].interest_amount, 2)
		self.assertEqual(calculated_bpi_amount, 79.45)

	def test_npa_for_loc(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2024-12-05",
		)

		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		# Test Limit Update
		loan.load_from_db()
		self.assertEqual(loan.utilized_limit_amount, 500000)
		self.assertEqual(loan.available_limit_amount, 0)

		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		create_process_loan_classification(posting_date="2024-10-05", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-05", 47523, loan_disbursement=disbursement.name
		)
		repayment_entry.submit()

		loan.load_from_db()

		self.assertEqual(loan.utilized_limit_amount, 500000 - repayment_entry.principal_amount_paid)
		self.assertEqual(loan.available_limit_amount, repayment_entry.principal_amount_paid)

	def test_dpd_calculation_for_non_loc_loan_without_disbursement(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			30,
			repayment_start_date="2024-10-05",
			posting_date="2024-09-15",
			rate_of_interest=10,
			applicant_type="Customer",
		).submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-09-15", repayment_start_date="2024-10-05"
		)
		loan_disbursement = frappe.db.get_value(
			"Loan Disbursement", {"against_loan": loan.name, "docstatus": 1}, "name"
		)

		process_daily_loan_demands(posting_date="2024-10-05", loan=loan.name)

		create_repayment_entry(
			loan.name, "2024-10-09", 3782, loan_disbursement=loan_disbursement
		).submit()

		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		create_repayment_entry(loan.name, "2024-11-10", 3782).submit()

		create_process_loan_classification(
			posting_date="2024-10-05", loan=loan.name, loan_disbursement=loan_disbursement
		)

		dpd_logs = frappe.db.sql(
			"""
			SELECT posting_date, days_past_due
			FROM `tabDays Past Due Log`
			WHERE loan = %s
			ORDER BY posting_date
			""",
			(loan.name),
			as_dict=1,
		)

		expected_dpd_values = {
			"2024-10-05": 1,
			"2024-10-06": 2,
			"2024-10-07": 3,
			"2024-10-08": 4,
			"2024-10-09": 0,
			"2024-10-10": 0,
			"2024-11-04": 0,
			"2024-11-05": 1,
			"2024-11-06": 2,
			"2024-11-07": 3,
			"2024-11-08": 4,
			"2024-11-09": 5,
			"2024-11-10": 0,
		}

		for log in dpd_logs:
			posting_date = log["posting_date"]
			dpd_value = log["days_past_due"]

			posting_date_str = posting_date.strftime("%Y-%m-%d")

			expected_dpd = expected_dpd_values.get(posting_date_str, 0)
			self.assertEqual(
				dpd_value,
				expected_dpd,
				f"DPD mismatch for {posting_date}: Expected {expected_dpd}, got {dpd_value}",
			)

	def test_dpd_calculation(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			30,
			repayment_start_date="2024-10-05",
			posting_date="2024-09-15",
			rate_of_interest=10,
			applicant_type="Customer",
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-09-15", repayment_start_date="2024-10-05"
		)
		process_daily_loan_demands(posting_date="2024-10-05", loan=loan.name)

		for date in ["2024-10-05", "2024-10-06", "2024-10-07", "2024-10-08", "2024-10-09", "2024-10-10"]:
			create_process_loan_classification(posting_date=date, loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-10-05", 3000)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-10-09", 782)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-11-05", 3000)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-11-10", 782)
		repayment_entry.submit()

		frappe.db.sql(
			"""
		update `tabDays Past Due Log` set days_past_due = -1 where loan = %s """,
			loan.name,
		)

		create_process_loan_classification(posting_date="2024-10-05", loan=loan.name)

		dpd_logs = frappe.db.sql(
			"""
			SELECT posting_date, days_past_due
			FROM `tabDays Past Due Log`
			WHERE loan = %s
			ORDER BY posting_date
			""",
			(loan.name),
			as_dict=1,
		)

		expected_dpd_values = {
			"2024-10-05": 1,
			"2024-10-06": 2,
			"2024-10-07": 3,
			"2024-10-08": 4,
			"2024-10-09": 0,  # Fully repaid
			"2024-10-10": 0,
			"2024-11-04": 0,
			"2024-11-05": 1,  # DPD starts again after repayment
			"2024-11-06": 2,
			"2024-11-07": 3,
			"2024-11-08": 4,
			"2024-11-09": 5,
			"2024-11-10": 0,  # Fully repaid
		}

		for log in dpd_logs:
			posting_date = log["posting_date"]
			dpd_value = log["days_past_due"]

			posting_date_str = posting_date.strftime("%Y-%m-%d")

			expected_dpd = expected_dpd_values.get(posting_date_str, 0)
			self.assertEqual(
				dpd_value,
				expected_dpd,
				f"DPD mismatch for {posting_date}: Expected {expected_dpd}, got {dpd_value}",
			)

		dpd_in_loan = frappe.db.get_value("Loan", loan.name, "days_past_due")
		self.assertEqual(dpd_in_loan, 0)

	def test_dpd_calculation_for_loc_loan(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			100000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2024-10-10",
			posting_date="2024-10-01",
			rate_of_interest=20,
			applicant_type="Customer",
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2025-12-05",
		)
		loan.submit()

		disbursement_1 = make_loan_disbursement_entry(
			loan.name, 60000, disbursement_date="2024-10-01", repayment_start_date="2024-10-10"
		)

		process_daily_loan_demands(posting_date="2024-10-10", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-10", 10000, loan_disbursement=disbursement_1.name
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-18", 592, loan_disbursement=disbursement_1.name
		)
		repayment_entry.submit()

		disbursement_2 = make_loan_disbursement_entry(
			loan.name, 40000, disbursement_date="2024-10-05", repayment_start_date="2024-10-15"
		)

		process_daily_loan_demands(posting_date="2024-10-15", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-15", 7000, loan_disbursement=disbursement_2.name
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-25", 61, loan_disbursement=disbursement_2.name
		)
		repayment_entry.submit()

		frappe.db.sql(
			"""
		update `tabDays Past Due Log` set days_past_due = -1 where loan = %s """,
			loan.name,
		)

		create_process_loan_classification(
			posting_date="2024-10-10", loan=loan.name, loan_disbursement=disbursement_1.name
		)
		create_process_loan_classification(
			posting_date="2024-10-15", loan=loan.name, loan_disbursement=disbursement_2.name
		)

		dpd_logs = frappe.db.sql(
			"""
			SELECT posting_date, loan_disbursement, days_past_due
			FROM `tabDays Past Due Log`
			WHERE loan = %s
			ORDER BY posting_date
			""",
			(loan.name,),
			as_dict=1,
		)

		expected_dpd_values = {
			("2024-10-15", disbursement_1.name): 6,
			("2024-10-24", disbursement_2.name): 10,
		}

		for log in dpd_logs:
			posting_date = log["posting_date"].strftime("%Y-%m-%d")
			disbursement = log["loan_disbursement"]
			dpd_value = log["days_past_due"]

			if (posting_date, disbursement) not in expected_dpd_values:
				continue

			expected_dpd = expected_dpd_values[(posting_date, disbursement)]

			self.assertEqual(
				dpd_value,
				expected_dpd,
				f"DPD mismatch for {posting_date} (Disbursement: {disbursement}): Expected {expected_dpd}, got {dpd_value}",
			)

	def test_interest_accrual_breaks(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-08-16",
			posting_date="2024-08-16",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-08-16"
		)

		set_loan_accrual_frequency("Daily")
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-08-20", company="_Test Company"
		)

		loan_interest_accruals = get_loan_interest_accrual(
			loan=loan.name, from_date="2024-08-16", to_date="2024-08-20"
		)
		expected_dates = [
			"2024-08-16",
			"2024-08-17",
			"2024-08-18",
			"2024-08-19",
			"2024-08-20",
		]
		expected_dates = [getdate(i) for i in expected_dates]
		accrual_dates = [getdate(i) for i in loan_interest_accruals]
		self.assertEqual(accrual_dates, expected_dates)

		set_loan_accrual_frequency("Weekly")
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-08-31", company="_Test Company"
		)

		loan_interest_accruals = get_loan_interest_accrual(
			loan=loan.name, from_date="2024-08-21", to_date="2024-08-31"
		)
		expected_dates = [
			"2024-08-25",
		]
		expected_dates = [getdate(i) for i in expected_dates]
		accrual_dates = [getdate(i) for i in loan_interest_accruals]
		self.assertEqual(accrual_dates, expected_dates)

		set_loan_accrual_frequency("Monthly")
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-10-31", company="_Test Company"
		)

		loan_interest_accruals = get_loan_interest_accrual(
			loan=loan.name, from_date="2024-09-01", to_date="2024-11-05"
		)
		expected_dates = [
			"2024-09-15",
			"2024-09-30",
			"2024-10-15",
			"2024-10-31",
		]
		expected_dates = [getdate(i) for i in expected_dates]
		accrual_dates = [getdate(i) for i in loan_interest_accruals]
		self.assertEqual(accrual_dates, expected_dates)

	def test_npa_marking_for_customer(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		customer = frappe.get_doc(get_customer_dict("NPA Customer 1")).insert()
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan1 = create_loan(
			customer.name,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-05",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan1.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan1.name, loan1.loan_amount, disbursement_date="2024-03-05", repayment_start_date="2024-04-05"
		)

		loan2 = create_loan(
			customer.name,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-07-05",
			posting_date="2024-06-05",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan2.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan2.name, loan2.loan_amount, disbursement_date="2024-06-05", repayment_start_date="2024-07-05"
		)

		process_daily_loan_demands(posting_date="2024-07-05", loan=loan1.name)
		create_process_loan_classification(
			posting_date="2024-07-06", loan=loan1.name, force_update_dpd_in_loan=1
		)

		loan1.load_from_db()
		loan2.load_from_db()
		customer_npa = frappe.get_value("Customer", customer.name, "is_npa")

		self.assertTrue(loan1.is_npa, "Loan 1 not marked as NPA")
		self.assertTrue(loan2.is_npa, "Loan 2 not marked as NPA")
		self.assertTrue(customer_npa, "Customer not marked as NPA")

		create_process_loan_classification(
			posting_date="2024-07-07", loan=loan1.name, force_update_dpd_in_loan=1
		)

	def test_broken_period_interest_update(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-04-05",
			posting_date="2024-02-20",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan.submit()

		# Daily accrual
		disbursement = make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-02-20", repayment_start_date="2024-04-05"
		)

		self.assertTrue(disbursement.broken_period_interest, "BPI not set in disbursement")
		self.assertTrue(disbursement.broken_period_interest_days, "BPI not set in disbursement")

	def test_backdate_payments_with_daily_repayment_frequency(self):
		set_loan_accrual_frequency("Daily")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			50000,
			"Repay Over Number of Periods",
			60,
			repayment_start_date="2025-04-01",
			posting_date="2025-03-31",
			rate_of_interest=27,
			applicant_type="Customer",
			repayment_frequency="Daily",
		)

		loan.submit()

		# Daily accrual
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2025-03-31",
			repayment_start_date="2025-04-01",
			repayment_frequency="Daily",
		)

		for repayment_date in [
			"2025-04-01",
			"2025-04-02",
			"2025-04-03",
			"2025-04-11",
		]:
			process_daily_loan_demands(posting_date=repayment_date, loan=loan.name)
			repayment_entry = create_repayment_entry(loan.name, repayment_date, 818)
			repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2025-04-11", 818)
		repayment_entry.submit()

	def test_loc_pre_payment_interest(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			2700000,
			"Repay Over Number of Periods",
			1,
			posting_date="2024-10-30",
			rate_of_interest=17.25,
			applicant_type="Customer",
			limit_applicable_start="2024-10-28",
			limit_applicable_end="2025-10-28",
		)
		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name,
			486324,
			disbursement_date="2024-11-27",
			repayment_start_date="2025-01-26",
			repayment_frequency="One Time",
		)
		disbursement.submit()

		repayment_entry = create_repayment_entry(
			loan.name,
			"2025-01-23",
			420568,
			loan_disbursement=disbursement.name,
			repayment_type="Pre Payment",
		)

		repayment_entry.save()
		repayment_entry.submit()

		loan.load_from_db()
		# Check Interest Amount
		pending_principal = loan.disbursed_amount - repayment_entry.principal_amount_paid
		interest_amount = flt((pending_principal * 17.25 * 3) / 36500, 2)

		repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "status": "Active", "docstatus": 1}
		)
		schedule_details = frappe.db.get_all(
			"Repayment Schedule", {"parent": repayment_schedule}, ["interest_amount"]
		)

		self.assertEqual(schedule_details[0].interest_amount, interest_amount)

	def test_npa_marking_for_customer_via_scheduler(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
			process_loan_classification_batch,
		)

		customer = frappe.get_doc(get_customer_dict("NPA Customer 1")).insert()
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan1 = create_loan(
			customer.name,
			"Term Loan Product 4",
			50000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-05",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan1.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan1.name, loan1.loan_amount, disbursement_date="2024-03-05", repayment_start_date="2024-04-05"
		)

		loan2 = create_loan(
			customer.name,
			"Term Loan Product 4",
			50000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2024-07-05",
			posting_date="2024-06-05",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan2.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan2.name, loan2.loan_amount, disbursement_date="2024-06-05", repayment_start_date="2024-07-05"
		)

		process_daily_loan_demands(posting_date="2024-07-05", loan=loan1.name)
		process_daily_loan_demands(posting_date="2024-07-05", loan=loan2.name)

		process_loan_classification_batch(
			open_loans=[loan1.name],
			posting_date="2024-07-06",
			loan_product=loan1.loan_product,
			classification_process=None,
			loan_disbursement=None,
			payment_reference=None,
			is_backdated=0,
			force_update_dpd_in_loan=1,
		)

		loan1.load_from_db()
		loan2.load_from_db()
		customer_npa = frappe.get_value("Customer", customer.name, "is_npa")

		self.assertTrue(loan1.is_npa, "Loan 1 not marked as NPA")
		self.assertTrue(loan2.is_npa, "Loan 2 not marked as NPA")
		self.assertTrue(customer_npa, "Customer not marked as NPA")

		# Repay one loan and check, loans should still be marked as NPA
		amount1 = calculate_amounts(against_loan=loan1.name, posting_date="2024-07-06")
		repayment = create_repayment_entry(loan1.name, "2024-07-06", amount1.get("payable_amount"))

		repayment.submit()

		loan1.load_from_db()
		loan2.load_from_db()
		customer_npa = frappe.get_value("Customer", customer.name, "is_npa")

		self.assertTrue(loan1.is_npa, "Loan 1 not marked as NPA")
		self.assertTrue(loan2.is_npa, "Loan 2 not marked as NPA")
		self.assertTrue(customer_npa, "Customer not marked as NPA")

		# Repay second loan and check, loans should be marked as non NPA this time
		amount2 = calculate_amounts(against_loan=loan2.name, posting_date="2024-07-06")

		repayment = create_repayment_entry(loan2.name, "2024-07-06", amount2.get("payable_amount"))

		repayment.submit()

		process_loan_classification_batch(
			open_loans=[loan1.name],
			posting_date="2024-07-06",
			loan_product=loan1.loan_product,
			classification_process=None,
			loan_disbursement=None,
			payment_reference=None,
			is_backdated=0,
			force_update_dpd_in_loan=1,
		)

		loan1.load_from_db()
		loan2.load_from_db()
		customer_npa = frappe.get_value("Customer", customer.name, "is_npa")

		self.assertFalse(loan1.is_npa, "Loan 1 not unmarked as NPA")
		self.assertFalse(loan2.is_npa, "Loan 2 not unmarked as NPA")
		self.assertFalse(customer_npa, "Customer not unmarked as NPA")

	def test_two_day_break_up_in_accrual_frequency(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-08-16",
			posting_date="2024-08-16",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-08-16"
		)

		set_loan_accrual_frequency("Daily")
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-08-16", company="_Test Company"
		)
		# weird bug where a two day difference in remaining accrual (18-16=2) creates a consolidated entry
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-08-19", company="_Test Company"
		)

		loan_interest_accruals = get_loan_interest_accrual(
			loan=loan.name, from_date="2024-08-16", to_date="2024-08-20"
		)
		expected_dates = [
			"2024-08-16",
			"2024-08-17",
			"2024-08-18",
			"2024-08-19",
		]
		expected_dates = [getdate(i) for i in expected_dates]
		accrual_dates = [getdate(i) for i in loan_interest_accruals]
		self.assertEqual(accrual_dates, expected_dates)

	def test_interest_accrual_gl_before_write_off(self):
		set_loan_accrual_frequency("Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2024-12-01",
			posting_date="2024-12-01",
			rate_of_interest=25,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-12-01", repayment_start_date="2024-12-01"
		)

		create_loan_write_off(loan.name, "2024-12-31", write_off_amount=250000)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-12-31", company="_Test Company"
		)

		gl_entries = frappe.db.get_all(
			"GL Entry", filters={"voucher_type": "Loan Interest Accrual", "against_voucher": loan.name}
		)

		self.assertEqual(len(gl_entries), 60)  # 30 days of interest accruals

	def test_interest_accrual_creates_suspense_jv_for_npa_loan(self):
		set_loan_accrual_frequency("Daily")
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		customer = frappe.get_doc(get_customer_dict("NPA Customer 1")).insert()
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan = create_loan(
			customer.name,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-05",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-05", repayment_start_date="2024-04-05"
		)

		process_daily_loan_demands(posting_date="2024-07-05", loan=loan.name)
		create_process_loan_classification(
			posting_date="2024-07-06", loan=loan.name, force_update_dpd_in_loan=1
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-07-06", loan=loan.name, company="_Test Company"
		)

		last_accrual_date = frappe.db.get_value(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 1},
			"posting_date",
			order_by="posting_date desc",
		)

		self.assertEqual(getdate(last_accrual_date), getdate("2024-07-06"))

	def test_overlapping_accrual_validation(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-08-16",
			posting_date="2024-08-16",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan.submit()
		disbursement = make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-08-16"
		)

		def make_accrual_entry(start_date, posting_date):
			start_date = get_datetime(start_date)
			posting_date = get_datetime(posting_date)
			accrual_doc = frappe.new_doc("Loan Interest Accrual")
			accrual_doc.loan = loan.name
			accrual_doc.loan_disbursement = disbursement.name
			accrual_doc.company = "_Test Company"
			accrual_doc.rate_of_interest = 8.5
			accrual_doc.start_date = start_date
			accrual_doc.posting_date = posting_date
			accrual_doc.interest_amount = 32
			accrual_doc.base_amount = 100000
			accrual_doc.additional_interest_amount = 0

			return accrual_doc

		original_accrual = make_accrual_entry("2024-08-20", "2024-08-25")
		original_accrual.submit()
		original_accrual.load_from_db()

		overlapping_accruals = [
			("2024-08-20", "2024-08-24"),  # same start date, but shorter
			("2024-08-20", "2024-08-26"),  # same start date, but longer
			("2024-08-19", "2024-08-25"),  # same end date, but longer
			("2024-08-21", "2024-08-25"),  # same end date, but shorter
			("2024-08-21", "2024-08-23"),  # inside the original accrual
			("2024-08-18", "2024-08-27"),  # the original accrual will fit inside this
			("2024-08-20", "2024-08-25"),  # same start and end dates
			("2024-08-25", "2024-08-30"),  # touching from the right
			("2024-08-18", "2024-08-25"),  # touching from the left
		]
		for start_date, posting_date in overlapping_accruals:
			accrual_entry = make_accrual_entry(start_date, posting_date)
			self.assertRaises(frappe.ValidationError, accrual_entry.submit)

		non_overlapping_accruals = [
			("2024-08-17", "2024-08-18"),  # to the left
			("2024-08-26", "2024-08-30"),  # to the right
		]
		for start_date, posting_date in non_overlapping_accruals:
			accrual_entry = make_accrual_entry(start_date, posting_date)
			accrual_entry.submit()

	def test_flat_rate_interest_method(self):
		loan = create_loan(
			"_Test Customer 1",
			"Flat Interest Rate Loan",
			12000,
			"Repay Over Number of Periods",
			4,
			"Customer",
			repayment_start_date="2024-11-01",
			posting_date="2024-10-01",
			rate_of_interest=10,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-01", repayment_start_date="2024-11-01"
		)

		expected_repayment_schedule = [
			["2024-11-01", 3000, 100, 3100],
			["2024-12-01", 3000, 100, 3100],
			["2025-01-01", 3000, 100, 3100],
			["2025-02-01", 3000, 100, 3100],
		]

		repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)

		for idx, schedule in enumerate(repayment_schedule.repayment_schedule):
			(
				expected_date,
				expected_principal,
				expected_interest,
				expected_total,
			) = expected_repayment_schedule[idx]
			self.assertEqual(
				getdate(schedule.payment_date), getdate(expected_date), f"Due date mismatch at index {idx}"
			)
			self.assertEqual(
				flt(schedule.principal_amount, 2),
				flt(expected_principal, 2),
				msg=f"Principal amount mismatch at index {idx}",
			)
			self.assertEqual(
				flt(schedule.interest_amount, 2),
				flt(expected_interest),
				msg=f"Interest amount mismatch at index {idx}",
			)
			self.assertEqual(
				flt(schedule.total_payment, 2),
				flt(expected_total, 2),
				msg=f"Total amount mismatch at index {idx}",
			)

	def test_loc_loan_pre_payment_closure(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			2700000,
			"Repay Over Number of Periods",
			1,
			posting_date="2024-10-30",
			rate_of_interest=17.25,
			applicant_type="Customer",
			limit_applicable_start="2024-10-28",
			limit_applicable_end="2025-10-28",
		)
		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name,
			335533,
			disbursement_date="2024-11-25",
			repayment_start_date="2025-01-24",
			repayment_frequency="One Time",
		)
		disbursement.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2025-01-23", loan=loan.name, company="_Test Company"
		)
		repayment_entry = create_repayment_entry(
			loan.name,
			"2025-01-23",
			344890,
			loan_disbursement=disbursement.name,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()

		disbursement.load_from_db()
		self.assertEqual(disbursement.status, "Closed")

		repayment_schedule_status = frappe.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "loan_disbursement": disbursement.name, "docstatus": 1},
			"status",
		)

		self.assertEqual(repayment_schedule_status, "Closed")

	def test_pre_payment_demand_booking(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			285000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-12-05",
			posting_date="2024-11-07",
			rate_of_interest=17,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-11-07", repayment_start_date="2024-12-05"
		)

		process_daily_loan_demands(posting_date="2024-12-05", loan=loan.name)

		repayment = create_repayment_entry(
			loan.name,
			"2024-12-05",
			27321,
			repayment_type="Pre Payment",
		)
		repayment.submit()
