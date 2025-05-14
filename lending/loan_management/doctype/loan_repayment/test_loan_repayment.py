# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, date_diff, get_datetime, getdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	calculate_amounts,
	get_amounts,
	init_amounts,
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
			loan=loan_a.name, posting_date=repayment_start_date, paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name,
			posting_date=add_months(repayment_start_date, 1),
			paid_amount=178025,
		).submit()

		create_repayment_entry(
			loan=loan_b.name, posting_date=repayment_start_date, paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 1), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()

		dates = [add_months(repayment_start_date, i) for i in range(5)]
		for date in dates:
			repayment_a = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_a.name, "posting_date": date}
			)
			repayment_b = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_b.name, "posting_date": date}
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

		create_repayment_entry(loan=loan_a.name, posting_date="2024-05-05", paid_amount=178025).submit()
		entry_to_be_deleted = create_repayment_entry(
			loan=loan_a.name,
			posting_date=add_months("2024-05-05", 1),
			paid_amount=178025,
		)
		entry_to_be_deleted.submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months("2024-05-05", 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months("2024-05-05", 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months("2024-05-05", 4), paid_amount=178025
		).submit()
		entry_to_be_deleted.load_from_db()
		entry_to_be_deleted.cancel()

		create_repayment_entry(loan=loan_b.name, posting_date="2024-05-05", paid_amount=178025).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months("2024-05-05", 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months("2024-05-05", 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months("2024-05-05", 4), paid_amount=178025
		).submit()

		dates = [add_months("2024-05-05", i) for i in [0, 2, 3, 4]]
		for date in dates:
			repayment_a = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_a.name, "posting_date": date}
			)
			repayment_b = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_b.name, "posting_date": date}
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
			"SUM(interest_amount)",
		)
		self.assertGreater(penal_interest, 0)
		create_repayment_entry(loan=loan.name, posting_date="2024-05-05", paid_amount=178025).submit()
		penal_interest = frappe.get_value(
			"Loan Interest Accrual",
			{"loan": loan.name, "interest_type": "Penal Interest", "docstatus": 1},
			"SUM(interest_amount)",
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

		payable_amount = get_amounts(init_amounts(), loan, "2024-09-01")["payable_amount"]
		payable_principal_amount = get_amounts(init_amounts(), loan, "2024-09-01")[
			"payable_principal_amount"
		]
		repayment_entry = create_repayment_entry(
			loan.name, "2024-09-01", payable_amount, repayment_type="Normal Repayment"
		)
		repayment_entry.submit()
		pending_principal_amount = get_amounts(
			init_amounts(), loan, timedelta(seconds=1) + get_datetime("2024-09-01")
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

		accrual_dates = demand_dates = [
			get_datetime(add_days("2024-09-01", i))
			for i in range(date_diff("2024-10-01", "2024-09-01") + 1)
		]  # one month's worth of dates. This is to cover the time period for the generated (and subsequently cancelled) demands

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
			loan=loan.name, posting_date="2025-05-05", paid_amount=payable_amount
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
			loan=loan.name, posting_date="2025-06-05", paid_amount=payable_amount
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
