# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import flt

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
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
from lending.tests.utils import LendingTestSuite


class TestLoanSecurityDeposit(LendingTestSuite):
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

	def test_security_deposit_adjustment_with_unbooked_interest(self):
		# Accrued interest not yet billed (unbooked_interest) should still count
		# as payable for a Security Deposit Adjustment.
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
			loan.name,
			loan.loan_amount,
			disbursement_date="2025-01-06",
			repayment_start_date="2025-02-05",
			withhold_security_deposit=1,
		)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-01-20", company="_Test Company"
		)

		amounts = calculate_amounts(loan.name, "2025-01-21", for_update=True)
		payable_amount = flt(amounts.get("payable_amount", 0), 2)
		unbooked_interest = flt(amounts.get("unbooked_interest", 0), 2)
		self.assertGreater(unbooked_interest, 0, "No unbooked interest accrued for test loan")

		security_deposit_before = frappe.db.get_value(
			"Loan Security Deposit", {"loan": loan.name, "docstatus": 1}, "available_amount"
		)

		amount_paid = flt(payable_amount + unbooked_interest, 2)
		repayment = create_repayment_entry(
			loan.name, "2025-01-21", amount_paid, repayment_type="Security Deposit Adjustment"
		)
		repayment.submit()

		self.assertEqual(repayment.docstatus, 1, "Repayment should submit")

		security_deposit_after = frappe.get_doc(
			"Loan Security Deposit", {"loan": loan.name, "docstatus": 1}
		)
		self.assertEqual(flt(security_deposit_after.allocated_amount, 2), amount_paid)
		self.assertEqual(
			flt(security_deposit_after.available_amount, 2),
			flt(security_deposit_before - amount_paid, 2),
		)

	def test_security_deposit_adjustment_books_unaccrued_interest_as_interest(self):
		# An adjustment amount that only fits within payable_amount + unbooked_interest
		# + unaccrued_interest must still be booked as interest, not principal or excess.
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
			loan.name,
			loan.loan_amount,
			disbursement_date="2025-01-06",
			repayment_start_date="2025-02-05",
			withhold_security_deposit=1,
		)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-01-20", company="_Test Company"
		)

		# posting_date is after the latest accrual, so unaccrued_interest applies.
		posting_date = "2025-01-25"
		unlocked_amounts = calculate_amounts(loan.name, posting_date, for_update=False)
		payable_amount = flt(unlocked_amounts.get("payable_amount", 0), 2)
		unbooked_interest = flt(unlocked_amounts.get("unbooked_interest", 0), 2)
		unaccrued_interest = flt(unlocked_amounts.get("unaccrued_interest", 0), 2)
		self.assertGreater(unaccrued_interest, 0, "No unaccrued interest projected for test loan")

		pending_principal_before = frappe.db.get_value("Loan", loan.name, "total_principal_paid") or 0

		amount_paid = flt(payable_amount + unbooked_interest + unaccrued_interest, 2)
		repayment = create_repayment_entry(
			loan.name, posting_date, amount_paid, repayment_type="Security Deposit Adjustment"
		)
		repayment.submit()

		self.assertEqual(
			flt(repayment.unbooked_interest_paid, 2),
			flt(unbooked_interest + unaccrued_interest, 2),
			"unaccrued_interest portion should be booked as interest",
		)
		self.assertEqual(flt(repayment.excess_amount, 2), 0, "No excess amount expected")

		pending_principal_after = frappe.db.get_value("Loan", loan.name, "total_principal_paid") or 0
		self.assertEqual(
			pending_principal_after,
			pending_principal_before,
			"unaccrued_interest portion should not be booked as principal",
		)
