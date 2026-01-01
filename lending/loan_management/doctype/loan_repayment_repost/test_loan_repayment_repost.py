# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
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


class TestLoanRepaymentRepost(IntegrationTestCase):
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

		create_repayment_entry(
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
