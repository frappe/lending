# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, add_months, flt, get_datetime, nowdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_write_off.loan_write_off import (
	get_write_off_recovery_details,
	get_write_off_waivers,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_demand_offset_order,
	create_loan,
	create_loan_write_off,
	create_repayment_entry,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)
from lending.tests.utils import LendingTestSuite


class TestLoanRepaymentClosureAndWaivers(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

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
			loan.name, "2024-12-31", 2597256.40, repayment_type="Write Off Recovery"
		).submit()

		loan.load_from_db()

		self.assertEqual(loan.total_principal_paid, 2500000)

		repayment_entry.cancel()
		loan.load_from_db()

		self.assertEqual(loan.total_principal_paid, 0)
		self.assertEqual(loan.status, "Written Off")

	def test_write_off_recovery_with_charges(self):
		"""Charge raised after write-off stays as an ordinary outstanding invoice, paid off along with principal and interest."""
		set_loan_accrual_frequency("Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			2,
			"Customer",
			repayment_start_date="2024-12-01",
			posting_date="2024-12-01",
			rate_of_interest=25,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-12-01", repayment_start_date="2024-12-01"
		)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-12-31", company="_Test Company"
		)

		create_loan_write_off(loan.name, "2024-12-31", write_off_amount=10000)

		# Charge raised after write-off is never part of the write-off
		# waiver, so it stays as an ordinary outstanding sales invoice.
		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-12-31",
				"value_date": "2024-12-31",
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 750}],
			}
		)
		sales_invoice.submit()

		charge_amount = 750
		waivers = get_write_off_waivers(loan.name, "2024-12-31")
		recovery = get_write_off_recovery_details(loan.name, "2024-12-31")
		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-12-31", payment_type="Write Off Recovery")
		pay_amount = (
			flt(amounts.get("pending_principal_amount"))
			+ flt(waivers.get("Interest Waiver")) - flt(recovery.get("total_interest"))
			+ flt(waivers.get("Penalty Waiver")) - flt(recovery.get("total_penalty"))
			+ flt(waivers.get("Charges Waiver")) - flt(recovery.get("total_charges"))
			+ flt(amounts.get("total_charges_payable"))
		)

		repayment_entry = create_repayment_entry(loan.name, "2024-12-31", pay_amount, repayment_type="Write Off Recovery")
		repayment_entry.submit()

		self.assertEqual(repayment_entry.total_charges_paid, charge_amount)

		payment_account_debit = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Loan Repayment",
				"voucher_no": repayment_entry.name,
				"account": repayment_entry.payment_account,
				"is_cancelled": 0,
			},
			pluck="debit",
		)
		self.assertEqual(flt(sum(payment_account_debit), 2), flt(repayment_entry.amount_paid, 2))

	def test_write_off_recovery_with_waived_charges(self):
		"""Charge raised before write-off is waived automatically, paid back with no invoice or repayment_details row."""
		set_loan_accrual_frequency("Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			2,
			"Customer",
			repayment_start_date="2024-12-01",
			posting_date="2024-12-01",
			rate_of_interest=25,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-12-01", repayment_start_date="2024-12-01"
		)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-12-31", company="_Test Company"
		)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-12-31",
				"value_date": "2024-12-31",
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 750}],
			}
		)
		sales_invoice.submit()

		create_loan_write_off(loan.name, "2024-12-31", write_off_amount=10000)

		charge_amount = 750
		waivers = get_write_off_waivers(loan.name, "2024-12-31")
		recovery = get_write_off_recovery_details(loan.name, "2024-12-31")
		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-12-31", payment_type="Write Off Recovery")
		pay_amount = (
			flt(amounts.get("pending_principal_amount"))
			+ flt(waivers.get("Interest Waiver")) - flt(recovery.get("total_interest"))
			+ flt(waivers.get("Penalty Waiver")) - flt(recovery.get("total_penalty"))
			+ flt(waivers.get("Charges Waiver")) - flt(recovery.get("total_charges"))
		)

		repayment_entry = create_repayment_entry(loan.name, "2024-12-31", pay_amount, repayment_type="Write Off Recovery")
		repayment_entry.submit()

		self.assertEqual(repayment_entry.total_charges_paid, charge_amount)
		self.assertFalse(
			any(d.demand_type == "Charges" for d in repayment_entry.repayment_details)
		)

		payment_account_debit = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Loan Repayment",
				"voucher_no": repayment_entry.name,
				"account": repayment_entry.payment_account,
				"is_cancelled": 0,
			},
			pluck="debit",
		)
		self.assertEqual(flt(sum(payment_account_debit), 2), flt(repayment_entry.amount_paid, 2))

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

		emi_dates = ["2025-02-05", "2025-03-05", "2025-04-05", "2025-05-05"]
		for emi_date in emi_dates:
			accrual_date = add_days(emi_date, -1)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=accrual_date, company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=emi_date)
			create_repayment_entry(loan.name, emi_date, 54889).submit()

		pre_payment_date = "2025-05-21"
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-05-20", company="_Test Company"
		)

		amounts = calculate_amounts(loan.name, pre_payment_date)
		unbooked_interest = amounts.get("unbooked_interest", 0)

		# Test 1: Partial pre-payment (half of unbooked interest)
		partial_amount = flt(unbooked_interest / 2, 2)
		create_repayment_entry(loan.name, pre_payment_date, partial_amount, repayment_type="Pre Payment").submit()

		demand_amount = frappe.db.get_value(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1, "demand_subtype": "Interest", "demand_date": pre_payment_date},
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
			amounts_before_full.get("unbooked_interest", 0) + amounts_before_full.get("unaccrued_interest", 0),
			2
		)
		second_payment_amount = flt(full_pending + 10000, 2)

		create_repayment_entry(loan.name, pre_payment_date, second_payment_amount, repayment_type="Pre Payment").submit()

		final_unbooked = calculate_amounts(loan.name, pre_payment_date)["unbooked_interest"]
		self.assertGreaterEqual(final_unbooked, 0, "Unbooked interest should not be negative after full pre-payment")

	def test_full_settlement(self):
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

	def test_full_settlement_creates_waiver_and_write_off(self):
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

		process_daily_loan_demands(posting_date="2024-09-05", loan=loan.name)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-09-05", company="_Test Company"
		)

		repayment_entry_1 = create_repayment_entry(
			loan.name, "2024-09-05 17:24:18", 374378.00, repayment_type="Normal Repayment"
		)
		repayment_entry_1.submit()
		repayment_entry_1.cancel()

		repayment_entry_2 = create_repayment_entry(
			loan.name, "2024-09-05 17:24:18", 1000000, repayment_type="Full Settlement"
		)
		repayment_entry_2.submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Settled")

		loan_repayment = frappe.db.get_value(
			"Loan Repayment",
			{"repayment_type": "Interest Waiver", "against_loan": loan.name, "docstatus": 1},
			"name",
		)
		self.assertTrue(loan_repayment, "Interest waiver entry not created")

		loan_writer_off = frappe.db.get_value(
			"Loan Write Off",
			{"loan": loan.name, "docstatus": 1},
			"name",
		)
		self.assertTrue(loan_writer_off, "Loan write off entry not created")

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
				"value_date": "2024-07-01",
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

	def test_closure_pre_payment(self):
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "excess_amount_acceptance_limit", 100)

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

		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		create_repayment_entry(
			loan.name,
			"2024-04-05",
			101945.80,
			repayment_type="Pre Payment",
		).submit()

		demand_count = frappe.db.count("Loan Demand", {"loan": loan.name, "docstatus": 1, "demand_type": "EMI"})
		self.assertEqual(demand_count, 3)

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

		posting_date = "2024-01-10"
		process_daily_loan_demands(posting_date=posting_date, loan=loan.name)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-01-20", company="_Test Company"
		)

		amounts = calculate_amounts(against_loan=loan.name, posting_date=posting_date)
		penalty_amount = amounts["penalty_amount"]
		penalty_waiver = create_repayment_entry(
			loan=loan.name,
			value_date=posting_date,
			paid_amount=penalty_amount,
			repayment_type="Penalty Waiver",
		)
		penalty_waiver.submit()
		self.assertEqual(penalty_waiver.unbooked_interest_paid, 0)

	def test_no_unbooked_interest_for_charges_waivers(self):
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
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)

		posting_date = "2024-01-10"
		process_daily_loan_demands(posting_date=posting_date, loan=loan.name)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-01-20", company="_Test Company"
		)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": self.applicant2,
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-01-10",
				"value_date": "2024-01-10",
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
			value_date=posting_date,
			paid_amount=charges_amount,
			repayment_type="Charges Waiver",
		)

		charges_waiver.submit()
		self.assertEqual(charges_waiver.unbooked_interest_paid, 0)

	def test_multi_draft_payment_closure(self):
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
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-27", repayment_start_date="2025-06-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2025-06-04", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2025-06-05")

		repayment1 = create_repayment_entry(
			loan.name,
			"2025-06-05",
			paid_amount=1540342.47,
		)

		repayment2 = create_repayment_entry(
			loan.name,
			"2025-06-05",
			paid_amount=1000000,
		)

		repayment1.submit()
		repayment2.submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")

	def test_full_settlement_waivers_and_write_off(self):
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

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-08-04", company="_Test Company"
		)

		process_daily_loan_demands(posting_date="2024-08-05", loan=loan.name)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-09-04", company="_Test Company"
		)

		process_daily_loan_demands(posting_date="2024-09-05", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-09-05", 1000000, repayment_type="Full Settlement"
		)
		repayment_entry.submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Settled")

		demands = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1},
			["outstanding_amount"],
		)
		for demand in demands:
			self.assertEqual(demand.outstanding_amount, 0)

	def test_prepayment_charge_payment(self):
		set_loan_accrual_frequency("Daily")
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
			penalty_charges_rate=12,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-07-05", repayment_start_date="2024-08-05"
		)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-09-05", 500, prepayment_charges=[{"charge": "Processing Fee", "amount": 500}]
		)
		repayment_entry.submit()

		repayment_entry.load_from_db()
		self.assertEqual(repayment_entry.total_charges_paid, 500)
		self.assertEqual(repayment_entry.repayment_details[0].demand_subtype, "Processing Fee")

	def test_due_details_api_closure_with_future_penalty(self):
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "write_off_amount", 0)
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "excess_amount_acceptance_limit", 2)
		set_loan_accrual_frequency("Daily")

		posting_date = "2024-01-05"
		repayment_start_date = "2024-01-05"

		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			10000,
			"Repay Over Number of Periods",
			3,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=12,
			penalty_charges_rate=25,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)

		process_daily_loan_demands(posting_date="2024-02-05", loan=loan.name)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-02-17", company="_Test Company"
		)

		closure_date = "2024-02-20"
		amounts = calculate_amounts(against_loan=loan.name, posting_date=closure_date, payment_type="Loan Closure")
		payable_amount = amounts["payable_amount"]

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-02-19", company="_Test Company"
		)

		create_repayment_entry(
			loan.name,
			closure_date,
			payable_amount,
		).submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")

	def test_add_charges_api(self):
		from lending.api import apply_charge

		frappe.db.set_value("Company", "_Test Company", "enable_loan_accounting", 0)

		posting_date = "2024-01-05"
		repayment_start_date = "2024-01-05"

		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			10000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=12,
			penalty_charges_rate=25,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)

		apply_charge(
			loan=loan.name,
			charge_type="Processing Fee",
			based_on="On Outstanding Principal",
			percentage=2,
			charge_applicable_date=posting_date
		)

		payable_charge = calculate_amounts(against_loan=loan.name, posting_date=posting_date)["total_charges_payable"]
		self.assertEqual(payable_charge, 200)

		frappe.db.set_value("Company", "_Test Company", "enable_loan_accounting", 0)

	def test_full_settlement_cannot_be_backdated(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2025-08-05",
			posting_date="2025-07-05",
			rate_of_interest=10,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-07-05", repayment_start_date="2025-08-05"
		)

		process_daily_loan_demands(posting_date="2025-09-05", loan=loan.name)

		create_repayment_entry(
			loan.name, "2025-09-10", 34314.00, repayment_type="Normal Repayment"
		).submit()

		with self.assertRaises(frappe.ValidationError):
			create_repayment_entry(
				loan.name, "2025-09-06", 100000, repayment_type="Full Settlement"
			)

	def test_no_repayment_after_full_settlement_except_waivers(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2025-08-05",
			posting_date="2025-07-05",
			rate_of_interest=10,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-07-05", repayment_start_date="2025-08-05"
		)

		process_daily_loan_demands(posting_date="2025-09-05", loan=loan.name)

		create_repayment_entry(
			loan.name, "2025-09-05", 100000, repayment_type="Full Settlement"
		).submit()

		with self.assertRaises(frappe.ValidationError):
			create_repayment_entry(
				loan.name, "2025-09-06", 5000, repayment_type="Normal Repayment"
			)

	def test_get_bulk_due_details(self):
		# get_bulk_due_details should return the same amounts as the per-loan
		# calculate_amounts. This test mixes every branch of the function in one
		# call: a term loan with demands, a term loan with penalty, a loan with a
		# security deposit, a loan with no demands yet (last_demand_date is None),
		# and a Line of Credit loan.
		from lending.loan_management.doctype.loan_repayment.loan_repayment import get_bulk_due_details

		posting_date = "2024-01-05"
		repayment_start_date = "2024-01-05"
		due_date = "2024-05-05"

		# Term loan with demands and interest accrued.
		term = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			4,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		term.submit()
		make_loan_disbursement_entry(
			term.name, term.loan_amount, disbursement_date=posting_date, repayment_start_date=repayment_start_date
		)
		process_loan_interest_accrual_for_loans(loan=term.name, posting_date=due_date, company="_Test Company")
		process_daily_loan_demands(loan=term.name, posting_date=due_date)

		# Term loan that runs past due so penalty builds up.
		penalty_loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			10000,
			"Repay Over Number of Periods",
			3,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=12,
			penalty_charges_rate=25,
		)
		penalty_loan.submit()
		make_loan_disbursement_entry(
			penalty_loan.name, penalty_loan.loan_amount, disbursement_date=posting_date, repayment_start_date=repayment_start_date
		)
		process_daily_loan_demands(loan=penalty_loan.name, posting_date="2024-03-05")
		process_loan_interest_accrual_for_loans(loan=penalty_loan.name, posting_date="2024-03-10", company="_Test Company")

		# Loan with an available security deposit.
		deposit_loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			5000,
			"Repay Over Number of Periods",
			12,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=12,
		)
		deposit_loan.submit()
		deposit_disbursement = make_loan_disbursement_entry(
			deposit_loan.name, deposit_loan.loan_amount, disbursement_date=posting_date, repayment_start_date=repayment_start_date
		)
		frappe.get_doc(
			{
				"doctype": "Loan Security Deposit",
				"loan": deposit_loan.name,
				"loan_disbursement": deposit_disbursement.name,
				"deposit_amount": 5200,
				"available_amount": 5200,
			}
		).submit()
		process_daily_loan_demands(loan=deposit_loan.name, posting_date=due_date)

		# Loan with no demands raised at all (last_demand_date is None).
		no_demand = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			4,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		no_demand.submit()
		make_loan_disbursement_entry(
			no_demand.name, no_demand.loan_amount, disbursement_date=posting_date, repayment_start_date=repayment_start_date
		)

		# Line of Credit loan with two disbursements.
		loc = create_loan(
			self.applicant2,
			"Term Loan Product 5",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=25,
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2024-12-05",
		)
		loc.submit()
		disb_a = make_loan_disbursement_entry(
			loc.name, 500000, disbursement_date=posting_date, repayment_start_date=repayment_start_date
		)
		disb_b = make_loan_disbursement_entry(
			loc.name, 500000, disbursement_date=posting_date, repayment_start_date=repayment_start_date
		)
		process_loan_interest_accrual_for_loans(loan=loc.name, posting_date=due_date, company="_Test Company")
		process_daily_loan_demands(loan=loc.name, posting_date=due_date)

		loans = [term.name, penalty_loan.name, deposit_loan.name, no_demand.name, loc.name]

		# For every loan, the bulk amounts must equal the per-loan calculate_amounts.
		# due_date is not compared: a loan with no demands reports None in bulk but a
		# date in the single path, so they legitimately differ.
		compare_keys = [
			"pending_principal_amount",
			"payable_principal_amount",
			"interest_amount",
			"penalty_amount",
			"total_charges_payable",
			"unbooked_interest",
			"available_security_deposit",
		]
		bulk = {row["loan"]: row for row in get_bulk_due_details(loans, due_date, consolidated="True")}
		self.assertEqual(set(bulk.keys()), set(loans))
		for loan in loans:
			single = calculate_amounts(against_loan=loan, posting_date=due_date)
			for key in compare_keys:
				self.assertEqual(flt(bulk[loan][key]), flt(single[key]), msg=f"{key} mismatch for {loan}")

		# The penalty and security deposit branches actually produced values.
		self.assertGreater(flt(bulk[penalty_loan.name]["penalty_amount"]), 0)
		self.assertEqual(flt(bulk[deposit_loan.name]["available_security_deposit"]), 5200)

		# Non-consolidated Line of Credit returns one row per disbursement.
		loc_rows = get_bulk_due_details([loc.name], due_date, consolidated=False)
		self.assertEqual({row.get("loan_disbursement") for row in loc_rows}, {disb_a.name, disb_b.name})

	def test_get_last_demand_date_map(self):
		# The bulk last_demand_date map (used by get_bulk_due_details) must return
		# the same value as the per-loan get_last_demand_date for each loan, and be
		# safe on empty input.
		from lending.loan_management.doctype.loan_repayment.utils import (
			get_last_demand_date,
			get_last_demand_date_map,
		)

		posting_date = "2024-01-05"
		repayment_start_date = "2024-01-05"
		due_date = "2024-03-05"

		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			4,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date=posting_date, repayment_start_date=repayment_start_date
		)
		process_daily_loan_demands(loan=loan.name, posting_date=due_date)

		date_map = get_last_demand_date_map([loan.name], due_date)
		self.assertEqual(date_map.get(loan.name), get_last_demand_date(due_date, loan=loan.name))

	def test_normal_repayment_with_validate_normal_repayment(self):
		posting_date = get_datetime("2024-04-18")
		repayment_start_date = get_datetime("2024-05-05")

		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			4,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=10,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date=add_months(posting_date, 1), company="_Test Company"
		)
		process_daily_loan_demands(loan=loan.name, posting_date=repayment_start_date)

		frappe.db.set_value("Loan Product", "Term Loan Product 4", "validate_normal_repayment", 1)
		self.addCleanup(
			lambda: frappe.db.set_value("Loan Product", "Term Loan Product 4", "validate_normal_repayment", 0)
		)

		payable_amount = calculate_amounts(loan.name, repayment_start_date)["payable_amount"]

		repayment = create_repayment_entry(
			loan=loan.name, value_date=repayment_start_date, paid_amount=payable_amount
		)
		repayment.submit()

		self.assertEqual(repayment.docstatus, 1)

	def test_partial_settlement_allocates_to_emi_interest(self):
		"""Partial Settlement must allocate to real Interest demand, not leave it unaccounted for."""
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			200000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			"2025-02-15",
			"2025-01-25",
			rate_of_interest=22,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-25", repayment_start_date="2025-02-15"
		)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-02-15", company="_Test Company"
		)
		process_daily_loan_demands(posting_date="2025-02-15", loan=loan.name)

		amounts = calculate_amounts(
			against_loan=loan.name, posting_date="2025-02-15", payment_type="Partial Settlement"
		)
		self.assertGreater(amounts["interest_amount"], 0, "test setup must leave EMI Interest demand due")

		repayment = create_repayment_entry(
			loan.name, "2025-02-15", amounts["payable_amount"], repayment_type="Partial Settlement"
		)
		repayment.submit()

		self.assertEqual(flt(repayment.principal_amount_paid, 2), flt(amounts["payable_principal_amount"], 2))
		self.assertEqual(flt(repayment.total_interest_paid, 2), flt(amounts["interest_amount"], 2))

		allocated = sum(d.paid_amount for d in repayment.get("repayment_details"))
		self.assertEqual(flt(allocated, 2), flt(repayment.amount_paid, 2))

	def test_partial_settlement_interest_first_order_does_not_double_pay(self):
		"""With an Interest-before-Principal offset order, the Interest step must not
		also get claimed again by the Principal step's unscoped demand match."""
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")
		create_demand_offset_order(
			"Test Interest First Settlement Order", ["Penalty", "Interest", "Principal", "Charges"]
		)
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_settlement_collection",
			"Test Interest First Settlement Order",
		)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			200000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			"2025-02-15",
			"2025-01-25",
			rate_of_interest=22,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-25", repayment_start_date="2025-02-15"
		)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2025-02-15", company="_Test Company"
		)
		process_daily_loan_demands(posting_date="2025-02-15", loan=loan.name)

		amounts = calculate_amounts(
			against_loan=loan.name, posting_date="2025-02-15", payment_type="Partial Settlement"
		)
		self.assertGreater(amounts["interest_amount"], 0, "test setup must leave EMI Interest demand due")

		repayment = create_repayment_entry(
			loan.name, "2025-02-15", amounts["payable_amount"], repayment_type="Partial Settlement"
		)
		repayment.submit()

		self.assertEqual(flt(repayment.total_interest_paid, 2), flt(amounts["interest_amount"], 2))
		self.assertEqual(flt(repayment.principal_amount_paid, 2), flt(amounts["payable_principal_amount"], 2))

		allocated = sum(d.paid_amount for d in repayment.get("repayment_details"))
		self.assertEqual(flt(allocated, 2), flt(repayment.amount_paid, 2))



def make_bank_account(gl_account):
	frappe.get_doc({"doctype": "Bank", "bank_name": "_Test Loan Bank"}).insert(ignore_if_duplicate=True)
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


def make_bank_transaction(bank_account, deposit=0, withdrawal=0, date=None, party_type=None, party=None):
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
