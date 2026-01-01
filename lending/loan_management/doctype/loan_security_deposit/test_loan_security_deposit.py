# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

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
)


class TestLoanSecurityDeposit(IntegrationTestCase):
	"""
	Integration tests for LoanSecurityDeposit.
	Use this class for testing interactions between multiple components.
	"""

	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_security_deposit_adjustment(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			4,
			"Customer",
			posting_date="2024-03-25",
			rate_of_interest=10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-03-25",
			repayment_start_date="2024-04-01",
			withhold_security_deposit=1,
		)

		process_daily_loan_demands(posting_date="2024-05-01", loan=loan.name)

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-05-01")
		payable_amount = round(float(amounts["payable_amount"] or 0.0), 2)

		repayment_entry_1 = create_repayment_entry(loan.name, "2024-05-01", payable_amount)
		repayment_entry_1.submit()

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-05-05")
		total_net_payable = round(
			float(amounts["unaccrued_interest"] or 0.0)
			+ float(amounts["interest_amount"] or 0.0)
			+ float(amounts["penalty_amount"] or 0.0)
			+ float(amounts["total_charges_payable"] or 0.0)
			- float(amounts["available_security_deposit"] or 0.0)
			+ float(amounts["unbooked_interest"] or 0.0)
			+ float(amounts["unbooked_penalty"] or 0.0)
			+ float(amounts["pending_principal_amount"] or 0.0),
			2,
		)

		loan_adjustment = frappe.get_doc(
			{
				"doctype": "Loan Adjustment",
				"loan": loan.name,
				"posting_date": "2024-05-05",
				"foreclosure_type": "Internal Foreclosure",
				"adjustments": [{"loan_repayment_type": "Normal Repayment", "amount": total_net_payable}],
			}
		)
		loan_adjustment.submit()

		repayment_entry_1.cancel()

		loan_security_deposit = frappe.db.get_value(
			"Loan Security Deposit",
			{"loan": loan.name, "docstatus": 1},
			["name", "allocated_amount", "available_amount"],
			as_dict=True,
		)

		security_deposit = frappe.get_doc("Loan Security Deposit", loan_security_deposit.name)

		security_deposit_repayment = frappe.db.get_value(
			"Loan Repayment",
			{
				"against_loan": loan.name,
				"docstatus": 1,
				"repayment_type": ("=", "Security Deposit Adjustment"),
			},
			["name", "amount_paid"],
			as_dict=True,
		)

		repayment_doc = frappe.get_doc("Loan Repayment", security_deposit_repayment.name)

		# Case 1: After cancelling the first repayment, repost was increasing allocated amount again.
		# Fix ensures security deposit update runs only when payable_amount is correct.
		self.assertEqual(flt(security_deposit.allocated_amount, 2), flt(repayment_doc.amount_paid, 2))

		# Case 2: When Security Deposit Adjustment is cancelled, allocated and available amounts now reset properly.
		repayment_doc.cancel()
		security_deposit.load_from_db()

		self.assertEqual(flt(security_deposit.allocated_amount, 2), 0)
		self.assertEqual(flt(security_deposit.available_amount, 2), flt(repayment_doc.amount_paid, 2))
