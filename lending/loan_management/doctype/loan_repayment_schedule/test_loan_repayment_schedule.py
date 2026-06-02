# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import add_days, flt, get_datetime, getdate

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	get_interest_for_term,
)
from lending.loan_management.doctype.loan_repayment_schedule.utils import (
	get_monthly_repayment_amount,
	get_repayment_periods,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.tests.test_utils import (
	create_loan,
	create_loan_partner,
	create_repayment_entry,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)
from lending.tests.utils import LendingTestSuite


class TestLoanRepaymentSchedule(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_correct_moratorium_periods_after_restructure(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			285000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-12-05",
			posting_date="2024-11-05",
			rate_of_interest=17,
			applicant_type="Customer",
			moratorium_tenure=3,
			moratorium_type="Principal",
		)
		loan.submit()
		loan.load_from_db()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-11-05", repayment_start_date="2024-12-05"
		)
		process_daily_loan_demands(loan=loan.name, posting_date="2025-12-05")

		LoanDemand = DocType("Loan Demand")

		loan_demand_amount = (
			frappe.qb.from_(LoanDemand)
			.select(fn.Sum(LoanDemand.demand_amount))
			.where((LoanDemand.loan == loan.name) & (LoanDemand.docstatus == 1))
		).run()[0][0] or 0

		repayment_entry = create_repayment_entry(
			loan=loan.name,
			value_date="2025-12-05",
			paid_amount=loan_demand_amount + 1000,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()
		repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1}
		)
		repayment_schedule_rows = repayment_schedule.get("repayment_schedule")
		num_of_rows = len(repayment_schedule_rows)
		self.assertEqual(num_of_rows, 15)
		monthly_repayment_amount = get_monthly_repayment_amount(285000, 17, 12, "Monthly")
		self.assertTrue(
			abs(repayment_schedule_rows[-1].total_payment - (monthly_repayment_amount + 1000) < 1000)
		)

	def test_payment_date_unchanged_with_same_day_prepayments(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2025-02-05",
			posting_date="2025-01-06",
			rate_of_interest=28,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-06", repayment_start_date="2025-02-05"
		)

		first_sched = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1}, "name", order_by="creation asc"
		)

		first_sched_pay_date = frappe.db.get_value(
			"Repayment Schedule",
			{"parent": first_sched, "idx": 1},
			["payment_date"],
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2025-05-05")

		create_repayment_entry(loan.name, "2025-05-05", 219556.00).submit()
		create_repayment_entry(loan.name, "2025-05-21", 2000, repayment_type="Pre Payment").submit()
		create_repayment_entry(loan.name, "2025-05-21", 1000, repayment_type="Pre Payment").submit()

		last_sched, last_sched_start_date = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "docstatus": 1, "status": "Active"},
			["name", "repayment_start_date"],
		)

		active_sched_pay_date = frappe.db.get_value(
			"Repayment Schedule",
			{"parent": last_sched, "idx": 1},
			["payment_date"],
		)

		new_start_date = frappe.db.get_value(
			"Loan Restructure",
			{"loan": loan.name, "docstatus": 1},
			["repayment_start_date"],
			order_by="creation desc",
		)

		self.assertEqual(new_start_date, last_sched_start_date)
		self.assertEqual(first_sched_pay_date, active_sched_pay_date)

	def test_accrual_breaks_for_advance_and_pre_payments(self):
		for frequency in ["Daily", "Weekly", "Monthly"]:
			set_loan_accrual_frequency(frequency)
			loan = create_loan(
				"_Test Customer 1",
				"Term Loan Product 4",
				285000,
				"Repay Over Number of Periods",
				12,
				repayment_start_date="2024-12-05",
				posting_date="2024-11-05",
				rate_of_interest=17,
				applicant_type="Customer",
				moratorium_tenure=3,
				moratorium_type="Principal",
			)
			loan.submit()
			loan.load_from_db()
			make_loan_disbursement_entry(
				loan.name, loan.loan_amount, disbursement_date="2024-11-05", repayment_start_date="2024-12-05"
			)
			repayment_entry = create_repayment_entry(
				loan=loan.name,
				value_date="2025-12-05",
				paid_amount=185000,
				repayment_type="Pre Payment",
			)
			repayment_entry.submit()

			payable_interest = get_interest_for_term(
				"_Test Company",
				17,
				285000,
				getdate("2024-11-05"),
				add_days(getdate("2025-12-05"), -1),
			)

			LoanInterestAccrual = DocType("Loan Interest Accrual")

			paid_interest = (
				frappe.qb.from_(LoanInterestAccrual)
				.select(fn.Sum(LoanInterestAccrual.interest_amount))
				.where(LoanInterestAccrual.loan == loan.name)
			).run()[0][0] or 0

			self.assertEqual(flt(paid_interest, 0), flt(payable_interest, 0))

	def test_moratorium_date_jump(self):
		for moratorium_type in ["Principal", "EMI"]:
			loan = create_loan(
				"_Test Customer 1",
				"Term Loan Product 4",
				200000,
				"Repay Over Number of Periods",
				12,
				repayment_start_date="2025-08-05",
				posting_date="2025-07-18",
				rate_of_interest=30,
				applicant_type="Customer",
				moratorium_tenure=3,
				moratorium_type=moratorium_type,
			)
			loan.submit()
			loan.load_from_db()
			make_loan_disbursement_entry(
				loan.name, loan.loan_amount, disbursement_date="2025-07-18", repayment_start_date="2025-08-05"
			)
			repayment_schedule = frappe.get_doc("Loan Repayment Schedule", {"loan": loan.name})
			self.assertEqual(repayment_schedule.repayment_start_date, getdate("2025-08-05"))

	def test_date_after_advance_payment_rescheduling(self):
		set_loan_accrual_frequency("Daily")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			285000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-12-10",
			posting_date="2024-11-05",
			rate_of_interest=17,
			applicant_type="Customer",
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-11-05", repayment_start_date="2024-12-10"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2024-12-10")

		create_repayment_entry(loan.name, "2024-12-10", 25994).submit()

		create_repayment_entry(loan.name, "2024-12-15", 25994, repayment_type="Advance Payment").submit()

		active_repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "docstatus": 1, "status": "Active"},
			"name",
		)

		next_payment_date = frappe.db.get_value(
			"Repayment Schedule",
			{"parent": active_repayment_schedule, "payment_date": (">=", "2024-12-15")},
			"payment_date",
			order_by="payment_date asc",
		)

		self.assertEqual(next_payment_date, getdate("2025-01-10"))

	def test_pre_payment_restructure_with_loan_partner_and_bpi(self):
		loan_partner = "Test Loan Partner 1"
		if not frappe.db.exists("Loan Partner", loan_partner):
			create_loan_partner(
				"Test Loan Partner 1",
				"Test Loan Partner 1",
				partner_loan_share_percentage=80,
				effective_date="2025-01-27",
				repayment_schedule_type="EMI (PMT) based",
				partner_base_interest_rate=10,
				organization_type="Centralized",
				fldg_limit_calculation_component="Disbursement",
				type_of_fldg_applicable="Fixed Deposit Only",
				fldg_fixed_deposit_percentage=10,
			)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			posting_date="2026-02-18",
			repayment_start_date="2026-03-05",
			rate_of_interest=29,
			loan_partner=loan_partner,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-02-04", repayment_start_date="2026-03-05"
		)

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2026-02-18 00:00:00"), 0.32, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		self.assertEqual(schedule[0].balance_loan_amount, loan_repayment_schedule.current_principal_amount)
		self.assertEqual(loan_repayment_schedule.repayment_periods, len(schedule))

	def test_no_cost_emi_calculation_with_bpi_treatment(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			117770,
			"Repay Fixed Amount per Period",
			"Customer",
			monthly_repayment_amount=40000,
			posting_date="2026-03-01",
			repayment_start_date="2026-07-04",
			rate_of_interest=9.5,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-03-01", repayment_start_date="2026-04-07"
		)

	def test_get_repayment_periods_with_zero_interest(self):
		self.assertEqual(get_repayment_periods(10000, 0, 10000, "Monthly"), 1)
