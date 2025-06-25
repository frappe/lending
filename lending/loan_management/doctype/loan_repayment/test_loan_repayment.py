# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, date_diff, flt, get_datetime, getdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	calculate_amounts,
	get_amounts,
	init_amounts,
	post_bulk_payments,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_loan,
	create_loan_write_off,
	create_repayment_entry,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)


class TestLoanRepayment(IntegrationTestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_in_between_payments(self):
		posting_date = get_datetime("2024-04-18")
		repayment_start_date = get_datetime("2024-05-05")
		loan_a = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan_b = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loans = [loan_a, loan_b]
		for loan in loans:
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=posting_date,
				repayment_start_date=repayment_start_date,
			)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=add_months(posting_date, 6), company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=add_months(repayment_start_date, 6))

		create_repayment_entry(
			loan=loan_a.name, value_date=repayment_start_date, paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, value_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, value_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, value_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name,
			value_date=add_months(repayment_start_date, 1),
			paid_amount=178025,
		).submit()

		create_repayment_entry(
			loan=loan_b.name, value_date=repayment_start_date, paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months(repayment_start_date, 1), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()

		dates = [add_months(repayment_start_date, i) for i in range(5)]
		for date in dates:
			repayment_a = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_a.name, "value_date": date}
			)
			repayment_b = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_b.name, "value_date": date}
			)

			self.assertEqual(repayment_a.principal_amount_paid, repayment_b.principal_amount_paid)
			self.assertEqual(repayment_a.pending_principal_amount, repayment_b.pending_principal_amount)
			self.assertEqual(repayment_a.interest_payable, repayment_b.interest_payable)

	def test_in_between_cancellations(self):
		loan_a = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date="2024-05-05",
			posting_date="2024-04-18",
			rate_of_interest=23,
		)

		loan_b = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date="2024-05-05",
			posting_date="2024-04-18",
			rate_of_interest=23,
		)

		loans = [loan_a, loan_b]
		for loan in loans:
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date="2024-04-18",
				repayment_start_date="2024-05-05",
			)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=add_months("2024-05-05", 6), company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=add_months("2024-05-05", 6))

		create_repayment_entry(loan=loan_a.name, value_date="2024-05-05", paid_amount=178025).submit()
		entry_to_be_deleted = create_repayment_entry(
			loan=loan_a.name,
			value_date=add_months("2024-05-05", 1),
			paid_amount=178025,
		)
		entry_to_be_deleted.submit()
		create_repayment_entry(
			loan=loan_a.name, value_date=add_months("2024-05-05", 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, value_date=add_months("2024-05-05", 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, value_date=add_months("2024-05-05", 4), paid_amount=178025
		).submit()
		entry_to_be_deleted.load_from_db()
		entry_to_be_deleted.cancel()

		create_repayment_entry(loan=loan_b.name, value_date="2024-05-05", paid_amount=178025).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months("2024-05-05", 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months("2024-05-05", 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months("2024-05-05", 4), paid_amount=178025
		).submit()

		dates = [add_months("2024-05-05", i) for i in [0, 2, 3, 4]]
		for date in dates:
			repayment_a = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_a.name, "value_date": date}
			)
			repayment_b = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_b.name, "value_date": date}
			)

			self.assertEqual(repayment_a.interest_payable, repayment_b.interest_payable)
			# self.assertEqual(repayment_a.principal_amount_paid, repayment_b.principal_amount_paid)
			# self.assertEqual(repayment_a.pending_principal_amount, repayment_b.pending_principal_amount)

	def test_cancelled_penalties_on_timely_backdated_repayment(self):
		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date="2024-05-05",
			posting_date="2024-04-18",
			rate_of_interest=23,
			penalty_charges_rate=12,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-04-18",
			repayment_start_date="2024-05-05",
		)
		process_daily_loan_demands(loan=loan.name, posting_date="2024-05-05")
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date=add_days("2024-05-05", 6), company="_Test Company"
		)
		penal_interest = frappe.get_value(
			"Loan Interest Accrual",
			{"loan": loan.name, "interest_type": "Penal Interest", "docstatus": 1},
			[{"SUM": "interest_amount"}],
		)
		self.assertGreater(penal_interest, 0)
		create_repayment_entry(loan=loan.name, value_date="2024-05-05", paid_amount=178025).submit()
		penal_interest = frappe.get_value(
			"Loan Interest Accrual",
			{"loan": loan.name, "interest_type": "Penal Interest", "docstatus": 1},
			[{"SUM": "interest_amount"}],
		)
		self.assertEqual(penal_interest, None)

	def test_demand_generation_upon_pre_payment(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 2",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-09-16",
			posting_date="2024-08-16",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-09-16"
		)

		process_daily_loan_demands(posting_date="2024-11-16", loan=loan.name)

		payable_amount = get_amounts(init_amounts(), loan.name, "2024-09-01")["payable_amount"]
		payable_principal_amount = get_amounts(init_amounts(), loan.name, "2024-09-01")[
			"payable_principal_amount"
		]
		repayment_entry = create_repayment_entry(
			loan.name, "2024-09-01", payable_amount, repayment_type="Normal Repayment"
		)
		repayment_entry.submit()
		pending_principal_amount = get_amounts(
			init_amounts(), loan.name, timedelta(seconds=1) + get_datetime("2024-09-01")
		)["pending_principal_amount"]
		repayment_entry = create_repayment_entry(
			loan.name,
			timedelta(seconds=1) + get_datetime("2024-09-01"),
			pending_principal_amount,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()

		generated_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1, "demand_subtype": "Principal"},
			pluck="demand_amount",
		)
		self.assertEqual(
			sorted(generated_demands), sorted([payable_principal_amount, pending_principal_amount])
		)
		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")

	def test_correct_generation_and_cancellation_of_demands_and_accruals(self):
		set_loan_accrual_frequency(
			"Daily"
		)  # just cuz daily accruals and daily normal accruals together look more pleasing to the eye
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 2",
			100000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-09-01",
			posting_date="2024-08-16",
			rate_of_interest=12,
			applicant_type="Customer",
			penalty_charges_rate=12,
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-09-01"
		)

		process_loan_interest_accrual_for_loans(posting_date="2024-09-01", loan=loan.name)
		process_daily_loan_demands(posting_date="2024-09-16", loan=loan.name)
		process_loan_interest_accrual_for_loans(posting_date="2024-10-01", loan=loan.name)

		payable_amount = get_amounts(init_amounts(), loan.name, "2024-09-01")["payable_amount"]

		accrual_dates = [
			get_datetime(add_days("2024-09-01", i))
			for i in range(date_diff("2024-10-01", "2024-09-01") + 1)
		]  # one month's worth of dates. This is to cover the time period for the generated (and subsequently cancelled) demands

		demand_dates = [
			get_datetime(add_days(add_days("2024-09-01", i), 1))
			for i in range(date_diff("2024-10-01", "2024-09-01") + 1)
		]

		generated_penal_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1, "demand_type": "Penalty"},
			pluck="demand_date",
			order_by="demand_date ASC",
		)
		generated_additional_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1, "demand_type": "Additional Interest"},
			pluck="demand_date",
			order_by="demand_date ASC",
		)
		generated_penal_accruals = frappe.db.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 1, "interest_type": "Penal Interest"},
			pluck="posting_date",
			order_by="posting_date ASC",
		)

		# Below checks if the penal accruals and penalty and additional interests are happening from "2024-09-01" to "2024-10-01"
		for idx, generated_penal_demand in enumerate(generated_penal_demands):
			self.assertEqual(demand_dates[idx], generated_penal_demand)
		for idx, generated_additional_demand in enumerate(generated_additional_demands):
			self.assertEqual(demand_dates[idx], generated_additional_demand)
		for idx, generated_penal_accrual in enumerate(generated_penal_accruals):
			self.assertEqual(accrual_dates[idx], generated_penal_accrual)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-09-01", payable_amount, repayment_type="Normal Repayment"
		)
		repayment_entry.submit()

		generated_penal_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 2, "demand_type": "Penalty"},
			pluck="demand_date",
			order_by="demand_date ASC",
		)
		generated_additional_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 2, "demand_type": "Additional Interest"},
			pluck="demand_date",
			order_by="demand_date ASC",
		)
		generated_penal_accruals = frappe.db.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 2, "interest_type": "Penal Interest"},
			pluck="posting_date",
			order_by="posting_date ASC",
		)

		for idx, generated_penal_demand in enumerate(generated_penal_demands):
			self.assertEqual(demand_dates[idx], generated_penal_demand)
		for idx, generated_additional_demand in enumerate(generated_additional_demands):
			self.assertEqual(demand_dates[idx], generated_additional_demand)
		for idx, generated_penal_accrual in enumerate(generated_penal_accruals):
			self.assertEqual(accrual_dates[idx], generated_penal_accrual)

	def test_backdated_correct_demand_amounts(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")
		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2025-05-05",
			posting_date="2025-04-11",
			penalty_charges_rate=25,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			500000,
			repayment_start_date="2025-05-05",
			disbursement_date="2025-04-11",
		)
		process_loan_interest_accrual_for_loans(
			posting_date="2025-06-05", loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date="2025-06-05", loan=loan.name)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2025-05-05")[
			"payable_amount"
		]
		repayment1 = create_repayment_entry(
			loan=loan.name, value_date="2025-05-05", paid_amount=payable_amount
		)
		repayment1.submit()

		demands = frappe.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1},
			["demand_amount", "outstanding_amount", "paid_amount", "demand_date"],
		)
		for demand in demands:
			if demand.demand_date > get_datetime("2025-05-05"):
				self.assertEqual(demand.outstanding_amount, demand.demand_amount)
				self.assertEqual(demand.paid_amount, 0)
			else:
				self.assertEqual(demand.outstanding_amount, 0)
				self.assertEqual(demand.paid_amount, demand.demand_amount)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2025-06-05")[
			"payable_amount"
		]
		repayment2 = create_repayment_entry(
			loan=loan.name, value_date="2025-06-05", paid_amount=payable_amount
		)
		repayment2.submit()

		demands = frappe.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1},
			["demand_amount", "outstanding_amount", "paid_amount", "demand_date"],
		)
		for demand in demands:
			self.assertEqual(demand.outstanding_amount, 0)
			self.assertEqual(demand.paid_amount, demand.demand_amount)

		repayment1.cancel()
		demands = frappe.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1},
			["demand_amount", "outstanding_amount", "paid_amount", "demand_date"],
		)
		for demand in demands:
			if demand.demand_date > get_datetime("2025-05-05"):
				self.assertEqual(demand.outstanding_amount, demand.demand_amount)
				self.assertEqual(demand.paid_amount, 0)
			else:
				self.assertEqual(demand.outstanding_amount, 0)
				self.assertEqual(demand.paid_amount, demand.demand_amount)

	def test_on_time_penal_cancellations(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")
		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2025-05-05",
			posting_date="2025-04-11",
			penalty_charges_rate=25,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			500000,
			repayment_start_date="2025-05-05",
			disbursement_date="2025-04-11",
		)
		process_daily_loan_demands(posting_date="2025-06-04", loan=loan.name)
		process_loan_interest_accrual_for_loans(
			posting_date="2025-06-04", loan=loan.name, company="_Test Company"
		)
		accrual_dates = []
		demand_dates = []
		current_date = get_datetime("2025-05-05")

		while getdate(current_date) < getdate("2025-06-05"):
			accrual_dates.append(current_date)
			current_date = add_days(current_date, 1)
			demand_dates.append(current_date)

		penal_accrual_dates = frappe.db.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "interest_type": "Penal Interest", "docstatus": 1},
			pluck="posting_date",
			order_by="posting_date",
		)
		penal_demand_dates = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "demand_type": "Penalty", "docstatus": 1},
			pluck="demand_date",
			order_by="demand_date",
		)
		self.assertEqual(accrual_dates, penal_accrual_dates)
		self.assertEqual(demand_dates, penal_demand_dates)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2025-05-05")[
			"payable_amount"
		]
		repayment = create_repayment_entry(
			loan=loan.name, value_date="2025-05-05", paid_amount=payable_amount
		)
		repayment.submit()
		penal_accrual_dates = frappe.db.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "interest_type": "Penal Interest", "docstatus": 2},
			pluck="posting_date",
			order_by="posting_date",
		)
		penal_demand_dates = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "demand_type": "Penalty", "docstatus": 2},
			pluck="demand_date",
			order_by="demand_date",
		)
		self.assertEqual(accrual_dates, penal_accrual_dates)
		self.assertEqual(demand_dates, penal_demand_dates)

	def test_value_dated_loan_repayment(self):
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

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-02-20", repayment_start_date="2024-04-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-04-01", loan=loan.name, company="_Test Company"
		)

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-04-01",
			100945.80,
		)
		repayment_entry.submit()

		self.assertEqual(repayment_entry.value_date, "2024-04-01")

		dates = frappe.get_all(
			"GL Entry",
			{
				"voucher_type": "Loan Repayment",
				"voucher_no": repayment_entry.name,
			},
			pluck="posting_date",
		)

		for posting_date in dates:
			self.assertEqual(posting_date, getdate())

	def test_loc_loan_unbooked_interest(self):
		set_loan_accrual_frequency("Daily")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			500000,
			"Repay Over Number of Periods",
			1,
			posting_date="2024-10-17",
			rate_of_interest=17,
			applicant_type="Customer",
			limit_applicable_start="2024-10-16",
			limit_applicable_end="2026-10-16",
		)
		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name,
			171000,
			disbursement_date="2024-11-30",
			repayment_start_date="2025-02-28",
			repayment_frequency="One Time",
		)
		disbursement.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-01",
			loan=loan.name,
			company="_Test Company",
			loan_disbursement=disbursement.name,
		)

		repayment_entry1 = create_repayment_entry(
			loan.name,
			"2024-12-02",
			3859,
			loan_disbursement=disbursement.name,
			repayment_type="Pre Payment",
		)
		repayment_entry1.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-02",
			loan=loan.name,
			company="_Test Company",
			loan_disbursement=disbursement.name,
		)

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-12-03",
			1930,
			loan_disbursement=disbursement.name,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-03",
			loan=loan.name,
			company="_Test Company",
			loan_disbursement=disbursement.name,
		)

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-12-04",
			1930,
			loan_disbursement=disbursement.name,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-04",
			loan=loan.name,
			company="_Test Company",
			loan_disbursement=disbursement.name,
		)

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-12-05",
			1930,
			loan_disbursement=disbursement.name,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-05",
			loan=loan.name,
			company="_Test Company",
			loan_disbursement=disbursement.name,
		)

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-12-06",
			1947,
			loan_disbursement=disbursement.name,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()

		accrual_dates = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 1},
			["posting_date", "start_date", "interest_amount"],
		)

		self.assertEqual(repayment_entry1.unbooked_interest_paid, 159.28)

		for accrual_date in accrual_dates:
			self.assertEqual(accrual_date.start_date, accrual_date.posting_date)

		frappe.get_doc(
			{
				"doctype": "Loan Repayment Repost",
				"loan": loan.name,
				"loan_disbursement": disbursement.name,
				"repost_date": "2024-12-02",
				"cancel_future_emi_demands": 1,
				"cancel_future_accruals_and_demands": 1,
			}
		).submit()

		interest_accrual_revised = frappe.db.get_value(
			"Loan Interest Accrual",
			{
				"loan": loan.name,
				"docstatus": 1,
				"posting_date": "2024-12-02",
				"interest_type": "Normal Interest",
			},
			"interest_amount",
		)

		self.assertEqual(interest_accrual_revised, 77.92)

	def test_bulk_payments(self):
		posting_date = get_datetime("2024-04-18")
		repayment_start_date = get_datetime("2024-05-05")
		loan_a = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan_b = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan_c = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loans = [loan_a, loan_b, loan_c]
		for loan in loans:
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=posting_date,
				repayment_start_date=repayment_start_date,
			)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=add_months(posting_date, 6), company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=add_months(repayment_start_date, 6))

		data = []
		for i in range(5):
			data.append(
				{
					"against_loan": loan_a.name,
					"value_date": add_months(repayment_start_date, i),
					"amount_paid": 178025,
				}
			)
		# Extra repayment because why not?
		for i in range(5):
			data.append(
				{
					"against_loan": loan_c.name,
					"value_date": add_months(repayment_start_date, i),
					"amount_paid": 178025 + i,
				}
			)
		post_bulk_payments(data)

		create_repayment_entry(
			loan=loan_b.name, value_date=repayment_start_date, paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months(repayment_start_date, 1), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, value_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()

		dates = [add_months(repayment_start_date, i) for i in range(5)]
		for date in dates:
			repayment_a = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_a.name, "value_date": date}
			)
			repayment_b = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_b.name, "value_date": date}
			)

			self.assertEqual(repayment_a.principal_amount_paid, repayment_b.principal_amount_paid)
			self.assertEqual(repayment_a.pending_principal_amount, repayment_b.pending_principal_amount)
			self.assertEqual(repayment_a.interest_payable, repayment_b.interest_payable)

	def test_bulk_repayment_logs(self):
		posting_date = get_datetime("2024-04-18")
		repayment_start_date = get_datetime("2024-05-05")
		loan_a = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan_b = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loans = [loan_a, loan_b]
		for loan in loans:
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=posting_date,
				repayment_start_date=repayment_start_date,
			)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=add_months(posting_date, 6), company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=add_months(repayment_start_date, 6))

		data = []
		for i in range(5):
			data.append(
				{
					"against_loan": loan_a.name,
					"value_date": add_months(repayment_start_date, i),
					"amount_paid": 178025,
				}
			)
		# This should fail (closed loan)
		frappe.db.set_value("Loan", loan_b.name, "status", "Closed")
		for i in range(5):
			data.append(
				{
					"against_loan": loan_b.name,
					"value_date": add_months(repayment_start_date, i),
					"amount_paid": 178025,
				}
			)
		post_bulk_payments(data)

		successful_log = frappe.get_doc("Bulk Repayment Log", {"loan": loan_a.name})
		failed_log = frappe.get_doc("Bulk Repayment Log", {"loan": loan_b.name})

		self.assertEqual(successful_log.status, "Success")
		self.assertEqual(failed_log.status, "Failure")

	def test_loan_repayment_cancel_with_amount_overlimit(self):
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "excess_amount_acceptance_limit", 100)
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

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

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-02-20", repayment_start_date="2024-04-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-04-05", loan=loan.name, company="_Test Company"
		)

		repayment = create_repayment_entry(loan.name, "2024-04-05", paid_amount=102000).submit()

		repayment.cancel()

		repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}, "name"
		)

		self.assertTrue(repayment_schedule)

	def test_advance_payment_before_first_payment(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			200000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2025-01-05",
			posting_date="2024-12-26",
			rate_of_interest=31,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-12-26", repayment_start_date="2025-01-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2025-01-02", loan=loan.name, company="_Test Company"
		)

		create_repayment_entry(
			loan.name, "2025-01-03", paid_amount=19596, repayment_type="Advance Payment"
		).submit()

		repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)

		self.assertEqual(
			repayment_schedule.get("repayment_schedule")[0].payment_date, getdate("2025-01-05")
		)

		self.assertEqual(repayment_schedule.get("repayment_schedule")[0].demand_generated, 1)

	def test_back_date_closure_payment_with_penalty_cancel(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			1,
			repayment_start_date="2025-06-05",
			posting_date="2025-01-26",
			rate_of_interest=19,
			applicant_type="Customer",
			penalty_charges_rate=36,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-27", repayment_start_date="2025-06-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2025-06-04", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2025-06-05")

		process_loan_interest_accrual_for_loans(
			posting_date="2025-06-05", loan=loan.name, company="_Test Company"
		)

		create_repayment_entry(
			loan.name,
			"2025-06-05",
			paid_amount=2540342.47,
		).submit()

		loan.load_from_db()

		self.assertEqual(loan.status, "Closed")

	def test_write_off_recovery_cancel(self):
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

		repayment_entry = create_repayment_entry(
			loan.name, "2024-12-31", 10000, repayment_type="Write Off Recovery"
		).submit()

		loan.load_from_db()

		self.assertEqual(loan.total_principal_paid, 10000)

		repayment_entry.cancel()

		loan.load_from_db()

		self.assertEqual(loan.total_principal_paid, 0)

	def test_pre_payment_with_partial_unbooked_interest(self):
		set_loan_accrual_frequency("Daily")

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

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-02-04", company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2025-02-05")

		create_repayment_entry(loan.name, "2025-02-05", 54889).submit()

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-03-04", company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2025-03-05")

		create_repayment_entry(loan.name, "2025-03-05", 54889).submit()

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-04-04", company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2025-04-05")

		create_repayment_entry(loan.name, "2025-04-05", 54889).submit()

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-05-04", company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2025-05-05")

		create_repayment_entry(loan.name, "2025-05-05", 54889).submit()

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-05-20", company="_Test Company"
		)

		create_repayment_entry(loan.name, "2025-05-21", 3327, repayment_type="Pre Payment").submit()

		demand_amount = frappe.db.get_value(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1, "demand_subtype": "Interest", "demand_date": "2025-05-21"},
			"paid_amount",
		)

		self.assertEqual(demand_amount, 3327)

		repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}, "name"
		)
		principal_amount, interest_amount = frappe.db.get_value(
			"Repayment Schedule",
			{"parent": repayment_schedule, "idx": 5},
			["principal_amount", "interest_amount"],
		)

		self.assertEqual(flt(principal_amount, 2), 37593.01)
		self.assertEqual(flt(interest_amount, 2), 17295.99)
