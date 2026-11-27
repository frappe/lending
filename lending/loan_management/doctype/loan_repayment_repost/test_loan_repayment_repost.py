# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, get_datetime

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
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


class TestLoanRepaymentRepost(FrappeTestCase):
	"""
	Integration tests for LoanRepaymentRepost.
	Use this class for testing interactions between multiple components.
	"""

	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_backdated_repayment_allocation_resets_on_repost(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			10000,
			"Repay Over Number of Periods",
			2,
			"Customer",
			"2025-02-15",
			"2025-01-25",
			rate_of_interest=10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-25", repayment_start_date="2025-02-15"
		)
		process_daily_loan_demands(posting_date="2025-02-15", loan=loan.name)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2025-02-15")[
			"payable_amount"
		]
		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2025-02-15 00:06:10"), payable_amount
		).submit()

		process_daily_loan_demands(posting_date="2025-03-15", loan=loan.name)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2025-03-20")[
			"payable_amount"
		]

		create_repayment_entry(
			loan.name, get_datetime("2025-03-20 00:06:10"), flt(payable_amount / 2, 2)
		).submit()

		create_repayment_entry(
			loan.name, get_datetime("2025-03-16 00:06:10"), flt(payable_amount / 2, 2)
		).submit()

		demands = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1},
			["outstanding_amount"],
		)
		for demand in demands:
			self.assertEqual(demand.outstanding_amount, 0)

	def test_repost_on_same_day_payments(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			10000,
			"Repay Over Number of Periods",
			2,
			"Customer",
			"2025-02-15",
			"2025-01-25",
			rate_of_interest=10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-25", repayment_start_date="2025-02-15"
		)
		process_daily_loan_demands(posting_date="2025-02-15", loan=loan.name)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2025-02-15")[
			"payable_amount"
		]

		create_repayment_entry(loan.name, "2025-02-15", payable_amount).submit()

		process_daily_loan_demands(posting_date="2025-03-15", loan=loan.name)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2025-03-20")[
			"payable_amount"
		]

		create_repayment_entry(loan.name, "2025-03-16", flt(payable_amount / 2, 2)).submit()

		create_repayment_entry(loan.name, "2025-03-16", flt(payable_amount / 2, 2)).submit()

		demands = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1},
			["outstanding_amount"],
		)
		for demand in demands:
			self.assertEqual(demand.outstanding_amount, 0)

	def test_repost_counts_only_payments_after_restructure(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Weekly")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 1",
			12000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			repayment_start_date="2025-02-05",
			posting_date="2025-01-06",
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-06", repayment_start_date="2025-02-05"
		)

		process_daily_loan_demands(posting_date="2025-03-05", loan=loan.name)
		payable_amount = calculate_amounts(loan.name, "2025-03-05")["payable_amount"]
		repayment = create_repayment_entry(loan.name, "2025-03-05", payable_amount)
		repayment.submit()

		restructure = frappe.new_doc("Loan Restructure")
		restructure.loan = loan.name
		restructure.restructure_type = "Normal Restructure"
		restructure.restructure_date = "2025-03-05"
		restructure.repayment_start_date = "2025-04-05"
		restructure.new_repayment_period_in_months = 6
		restructure.submit()
		restructure.status = "Approved"
		restructure.save()

		process_daily_loan_demands(posting_date="2025-04-05", loan=loan.name)
		payable_amount = calculate_amounts(loan.name, "2025-04-05")["payable_amount"]
		create_repayment_entry(loan.name, "2025-04-05", payable_amount).submit()

		fields = ["total_principal_paid", "total_amount_paid", "excess_amount_paid"]
		before = frappe.db.get_value("Loan", loan.name, fields, as_dict=1)
		schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan_restructure": restructure.name, "docstatus": 1}, "name"
		)

		frappe.get_doc(
			{"doctype": "Loan Repayment Repost", "loan": loan.name, "repost_date": "2025-03-06"}
		).submit()

		after = frappe.db.get_value("Loan", loan.name, fields, as_dict=1)
		for field in fields:
			self.assertEqual(flt(after[field], 2), flt(before[field], 2))
		self.assertEqual(frappe.db.get_value("Loan Repayment Schedule", schedule, "status"), "Active")

		repost = frappe.get_doc(
			{"doctype": "Loan Repayment Repost", "loan": loan.name, "repost_date": "2025-03-05"}
		)
		self.assertRaises(frappe.ValidationError, repost.submit)
		with self.assertRaises(frappe.ValidationError):
			create_repayment_entry(loan.name, "2025-03-04", 500).submit()
		self.assertRaises(
			frappe.ValidationError, frappe.get_doc("Loan Repayment", repayment.name).cancel
		)
