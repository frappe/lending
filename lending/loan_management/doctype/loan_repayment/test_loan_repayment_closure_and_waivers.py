# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, flt, nowdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
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
	make_loan_disbursement_entry,
	set_loan_accrual_frequency,
)
from lending.tests.utils import LendingTestSuite


class TestLoanRepaymentClosureAndWaivers(LendingTestSuite):
	applicant2 = "_Test Loan Customer"

	@classmethod
	def make_class_data(cls):
		set_loan_accrual_frequency("Weekly")

	def test_write_off_recovery_cancel(self):
		set_loan_accrual_frequency("Monthly")

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
			loan.name, "2024-12-31", 2597256.40, repayment_type="Write Off Recovery"
		).submit()

		loan.load_from_db()

		self.assertEqual(loan.total_principal_paid, 2500000)

		repayment_entry.cancel()
		loan.load_from_db()

		self.assertEqual(loan.total_principal_paid, 0)
		self.assertEqual(loan.status, "Written Off")

	def test_pre_payment_with_partial_unbooked_interest(self):
		set_loan_accrual_frequency("Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2026-06-05",
			posting_date="2026-05-06",
			rate_of_interest=28,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-05-06", repayment_start_date="2026-06-05"
		)

		emi_dates = ["2026-06-05", "2026-07-05", "2026-08-05", "2026-09-05"]
		for emi_date in emi_dates:
			accrual_date = add_days(emi_date, -1)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=accrual_date, company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=emi_date)
			create_repayment_entry(loan.name, emi_date, 54889).submit()

		pre_payment_date = "2026-09-21"
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2026-09-20", company="_Test Company"
		)

		amounts = calculate_amounts(loan.name, pre_payment_date)
		unbooked_interest = amounts.get("unbooked_interest", 0)

		# Test 1: Partial pre-payment (half of unbooked interest)
		partial_amount = flt(unbooked_interest / 2, 2)
		create_repayment_entry(
			loan.name, pre_payment_date, partial_amount, repayment_type="Pre Payment"
		).submit()

		demand_amount = frappe.db.get_value(
			"Loan Demand",
			{
				"loan": loan.name,
				"docstatus": 1,
				"demand_subtype": "Interest",
				"demand_date": pre_payment_date,
			},
			"paid_amount",
		)
		self.assertEqual(demand_amount, partial_amount)

		remaining_unbooked = calculate_amounts(loan.name, pre_payment_date)["unbooked_interest"]
		self.assertEqual(flt(remaining_unbooked, 2), flt(unbooked_interest - partial_amount, 2))

		# Test 2: Additional partial pre-payment
		create_repayment_entry(loan.name, pre_payment_date, 1000, repayment_type="Pre Payment").submit()
		remaining_unbooked = calculate_amounts(loan.name, pre_payment_date)["unbooked_interest"]
		self.assertEqual(flt(remaining_unbooked, 2), flt(unbooked_interest - partial_amount - 1000, 2))

		# Test 3: Full pre-payment clearing remaining interest + principal
		amounts_before_full = calculate_amounts(loan.name, pre_payment_date)
		full_pending = flt(
			amounts_before_full.get("unbooked_interest", 0)
			+ amounts_before_full.get("unaccrued_interest", 0),
			2,
		)
		second_payment_amount = flt(full_pending + 10000, 2)

		create_repayment_entry(
			loan.name, pre_payment_date, second_payment_amount, repayment_type="Pre Payment"
		).submit()

		final_unbooked = calculate_amounts(loan.name, pre_payment_date)["unbooked_interest"]
		self.assertGreaterEqual(
			final_unbooked, 0, "Unbooked interest should not be negative after full pre-payment"
		)

	def test_loan_auto_closure_with_charge_under_limit(self):
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "write_off_amount", 1000)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			5000,
			"Repay Over Number of Periods",
			1,
			"Customer",
			"2024-07-15",
			"2024-06-25",
			10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-06-25", repayment_start_date="2024-07-15"
		)
		process_daily_loan_demands(posting_date="2025-01-05", loan=loan.name)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-07-01",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 50}],
			}
		)
		sales_invoice.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-07-15", 5068)
		repayment_entry.submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")

	def test_closure_payment_demand_cancel(self):
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
			101945.80,
		)
		repayment_entry.submit()
		repayment_entry.cancel()

		demands = frappe.db.get_all(
			"Loan Demand", {"loan_repayment": repayment_entry.name, "docstatus": 2}, pluck="name"
		)
		self.assertEqual(len(demands), 2)

	def test_no_unbooked_interest_for_penalty_waivers(self):
		set_loan_accrual_frequency("Daily")

		posting_date = "2024-01-05"
		repayment_start_date = "2024-01-05"

		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
			penalty_charges_rate=45,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)

		posting_date = "2024-04-10"
		process_daily_loan_demands(posting_date=posting_date, loan=loan.name)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-04-20", company="_Test Company"
		)

		amounts = calculate_amounts(against_loan=loan.name, posting_date=posting_date)
		penalty_amount = amounts["penalty_amount"]
		penalty_waiver = create_repayment_entry(
			loan=loan.name,
			posting_date=posting_date,
			paid_amount=penalty_amount,
			repayment_type="Penalty Waiver",
		)
		penalty_waiver.submit()
		self.assertEqual(penalty_waiver.unbooked_interest_paid, 0)

	def test_no_unbooked_interest_for_charges_waivers(self):
		set_loan_accrual_frequency("Daily")

		posting_date = "2024-01-05"
		repayment_start_date = "2024-01-05"

		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
			penalty_charges_rate=45,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)

		posting_date = "2024-04-10"
		process_daily_loan_demands(posting_date=posting_date, loan=loan.name)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-04-20", company="_Test Company"
		)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": self.applicant2,
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-04-10",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 5000}],
			}
		)
		sales_invoice.submit()

		amounts = calculate_amounts(against_loan=loan.name, posting_date=posting_date)

		charges_amount = amounts["total_charges_payable"]
		charges_waiver = create_repayment_entry(
			loan=loan.name,
			posting_date=posting_date,
			paid_amount=charges_amount,
			repayment_type="Charges Waiver",
		)

		charges_waiver.submit()
		self.assertEqual(charges_waiver.unbooked_interest_paid, 0)


def make_bank_account(gl_account):
	frappe.get_doc({"doctype": "Bank", "bank_name": "_Test Loan Bank"}).insert(
		ignore_if_duplicate=True
	)
	bank_account = frappe.get_doc(
		{
			"doctype": "Bank Account",
			"account_name": "_Test Loan Repayment Account",
			"bank": "_Test Loan Bank",
			"account": gl_account,
			"company": "_Test Company",
			"is_company_account": 1,
		}
	).insert(ignore_if_duplicate=True)

	return bank_account.name


def make_bank_transaction(
	bank_account, deposit=0, withdrawal=0, date=None, party_type=None, party=None
):
	return frappe.get_doc(
		{
			"doctype": "Bank Transaction",
			"bank_account": bank_account,
			"company": "_Test Company",
			"date": date or nowdate(),
			"deposit": deposit,
			"withdrawal": withdrawal,
			"currency": "INR",
			"party_type": party_type,
			"party": party,
		}
	).submit()


class TestDisbursedLoanFullSettlement(LendingTestSuite):
	@classmethod
	def make_class_data(cls):
		set_loan_accrual_frequency("Weekly")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2000000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-08-05",
			posting_date="2024-07-05",
			rate_of_interest=22,
			applicant_type="Customer",
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-07-05", repayment_start_date="2024-08-05"
		)
		cls.loan = loan.name

	def test_full_settlement(self):
		loan = frappe.get_doc("Loan", self.loan)

		process_daily_loan_demands(posting_date="2024-09-05", loan=loan.name)
		repayment_entry = create_repayment_entry(
			loan.name, "2024-08-05", 1000000, repayment_type="Full Settlement"
		)
		repayment_entry.submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Settled")

		repayment_entry.cancel()

		loan.load_from_db()
		self.assertEqual(loan.status, "Disbursed")

		create_repayment_entry(
			loan.name, "2024-08-05", 200000, repayment_type="Partial Settlement"
		).submit()

		create_repayment_entry(
			loan.name, "2024-08-05", 1000000, repayment_type="Full Settlement"
		).submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Settled")
