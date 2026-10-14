# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import add_days, add_months, flt, get_datetime, nowdate, random_string

from erpnext.selling.doctype.customer.test_customer import get_customer_dict

from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	calculate_amounts,
	process_pending_credit_notes,
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
	create_secured_demand_loan,
	loan_classification_ranges,
	make_loan_disbursement_entry,
	set_loan_accrual_frequency,
	set_loan_settings_in_company,
	setup_loan_demand_offset_order,
)
from lending.tests.utils import LendingTestSuite


class TestLoanWriteOffAndSettlement(LendingTestSuite):
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

	def test_loan_write_off_limit(self):
		loan = create_secured_demand_loan(self.applicant2)
		self.assertEqual(loan.loan_amount, 1000000)
		repayment_date = "2019-11-01"

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * 31) / (36500)
		process_loan_interest_accrual_for_loans(
			posting_date=add_days("2019-11-01", -1), loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date="2019-11-01", loan=loan.name)
		# repay 50 less so that it can be automatically written off
		repayment_entry = create_repayment_entry(
			loan.name,
			repayment_date,
			flt(loan.loan_amount + accrued_interest_amount - 50),
		)

		repayment_entry.submit()

		# -50 because shortfall_amount
		self.assertEqual(flt(repayment_entry.excess_amount, 0), -50)
		interest_waiver_account = frappe.db.get_value(
			"Loan Product", "Demand Loan", "interest_waiver_account"
		)
		gl_data = frappe.db.get_value(
			"GL Entry",
			{
				"voucher_no": repayment_entry.name,
				"voucher_type": "Loan Repayment",
				"account": interest_waiver_account,
			},
			["debit", "credit"],
			as_dict=1,
		)
		self.assertEqual(flt(gl_data.debit, 0), 50)
		self.assertEqual(flt(gl_data.credit, 0), 0)

	def test_loan_write_off_recovery(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)

		repayment = create_repayment_entry(
			loan.name, "2024-12-05", 1000000, repayment_type="Write Off Recovery"
		)
		repayment.submit()

		loan_status = frappe.db.get_value("Loan", loan.name, "status")
		self.assertEqual(loan_status, "Written Off")

		gl_entries = frappe.db.get_all(
			"GL Entry",
			filters={"voucher_no": repayment.name},
			fields=["account", "debit", "credit"],
		)

		expected_entries = [
			{"account": "Payment Account - _TC", "debit": 1000000, "credit": 0},
			{"account": "Write Off Recovery - _TC", "debit": 0, "credit": 1000000},
		]

		for expected in expected_entries:
			self.assertIn(expected, gl_entries, f"Missing GL entry: {expected}")

	def test_loan_write_off_settlement(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)

		repayment = create_repayment_entry(
			loan.name, "2025-01-05", 1500000, repayment_type="Write Off Settlement"
		)
		repayment.submit()

		loan_status = frappe.db.get_value("Loan", loan.name, "status")
		self.assertEqual(loan_status, "Settled")

		gl_entries = frappe.db.get_all(
			"GL Entry",
			filters={"voucher_no": repayment.name},
			fields=["account", "debit", "credit"],
		)

		expected_entries = [
			{"account": "Payment Account - _TC", "debit": 1500000, "credit": 0},
			{"account": "Write Off Recovery - _TC", "debit": 0, "credit": 1500000},
		]

		for expected in expected_entries:
			self.assertIn(expected, gl_entries, f"Missing GL entry: {expected}")

	def test_principal_amount_paid(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(
			loan.name, "2024-04-05", 60000, repayment_type="Pre Payment"
		)

		repayment_entry.submit()
		repayment_entry.load_from_db()

		extra_amount_paid = repayment_entry.amount_paid - repayment_entry.payable_amount
		total_principal_paid = repayment_entry.payable_principal_amount + extra_amount_paid

		self.assertEqual(flt(repayment_entry.principal_amount_paid, 1), flt(total_principal_paid, 1))

	def test_shortfall_loan_close_limit(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			50000,
			"Repay Over Number of Periods",
			2,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-04-05", 25784)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 25732.10)
		repayment_entry.submit()

	def test_excess_loan_close_limit(self):
		frappe.db.set_value(
			"Loan Product",
			"Term Loan Product 4",
			"customer_refund_account",
			"Customer Refund Account - _TC",
		)
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			2,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-04-05", 257840)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-05", 257950.97, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

	def test_cancellation_of_resulting_repayments_after_cancelling_full_settlements(self):
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
			loan.name, "2024-08-05", 100000, repayment_type="Full Settlement"
		)
		repayment_entry.submit()
		repayment_entry.cancel()
		closed_docs = frappe.db.get_all(
			"Loan Repayment",
			{
				"posting_date": (">=", repayment_entry.posting_date),
				"against_loan": repayment_entry.against_loan,
				"repayment_type": (
					"in",
					[
						"Interest Waiver",
						"Penalty Waiver",
						"Charges Waiver",
					],
				),
			},
			"docstatus",
			order_by="posting_date",
		)
		for closed_doc in closed_docs:
			self.assertEqual(2, closed_doc.docstatus)

	def test_cancellation_of_resulting_repayments_after_cancelling_full_settlements_for_loc(self):
		# makes two disbursements and corresponding full settlements and cancel one of them
		# checks if only the waivers for the cancelled full settlement are cancelled

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			60000,
			"Repay Over Number of Periods",
			4,
			repayment_start_date="2024-10-10",
			posting_date="2024-10-01",
			rate_of_interest=20,
			applicant_type="Customer",
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2025-12-05",
		)
		loan.submit()

		disbursement_1 = make_loan_disbursement_entry(
			loan.name, 36000, disbursement_date="2024-10-01", repayment_start_date="2024-10-10"
		)

		process_daily_loan_demands(posting_date="2024-10-10", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-10", 10000, loan_disbursement=disbursement_1.name
		)
		repayment_entry.submit()

		disbursement_2 = make_loan_disbursement_entry(
			loan.name, 24000, disbursement_date="2024-10-05", repayment_start_date="2024-10-15"
		)

		process_daily_loan_demands(posting_date="2024-10-15", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-15", 7000, loan_disbursement=disbursement_2.name
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-10-25",
			4000,
			repayment_type="Full Settlement",
			loan_disbursement=disbursement_1.name,
		)
		repayment_entry.submit()
		repayment_entry.cancel()

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-10-25 00:10:00",
			4000,
			repayment_type="Full Settlement",
			loan_disbursement=disbursement_2.name,
		)
		repayment_entry.submit()

		docs = frappe.db.get_all(
			"Loan Repayment",
			{
				"posting_date": (">=", repayment_entry.posting_date),
				"against_loan": repayment_entry.against_loan,
				"repayment_type": (
					"in",
					[
						"Interest Waiver",
						"Penalty Waiver",
						"Charges Waiver",
					],
				),
			},
			["docstatus", "loan_disbursement"],
			order_by="posting_date",
		)
		for doc in docs:
			if doc.loan_disbursement == disbursement_1.name:
				self.assertEqual(2, doc.docstatus)
			else:
				self.assertEqual(1, doc.docstatus)

	def test_backdated_pre_payment(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 2",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-08-16",
			posting_date="2024-08-16",
			rate_of_interest=8.5,
			applicant_type="Customer",
			moratorium_tenure=1,
			moratorium_type="Principal",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-08-16"
		)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-25", 15000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-11-01", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-11-16", 138.90, repayment_type="Normal Repayment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-12-01", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-11-26", 15000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

	def test_excess_amount_for_waiver(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
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
				"posting_date": "2025-01-15",
				"value_date": "2025-01-15",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 5000}],
			}
		)
		sales_invoice.submit()

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2025-01-16 00:03:10"), 106684.69
		)
		repayment_entry.submit()

		loan_adjustment = frappe.get_doc(
			{
				"doctype": "Loan Adjustment",
				"loan": loan.name,
				"posting_date": get_datetime("2025-01-16 00:06:10"),
				"adjustments": [{"loan_repayment_type": "Charges Waiver", "amount": 4900}],
			}
		)
		loan_adjustment.submit()

		process_pending_credit_notes()

		credit_notes = frappe.get_all(
			"Sales Invoice",
			filters={"loan": loan.name, "is_return": 1, "status": "Return"},
			fields=["name", "grand_total", "return_against"],
		)

		original_invoice_total = frappe.db.get_value("Sales Invoice", sales_invoice.name, "grand_total")

		total_credit_note_sum = sum(abs(flt(cr["grand_total"])) for cr in credit_notes)

		if total_credit_note_sum < original_invoice_total:
			missing_amount = original_invoice_total - total_credit_note_sum
			self.assertTrue(
				total_credit_note_sum >= original_invoice_total,
				f"Credit note is missing amount: {missing_amount}.",
			)

		outstanding_demand = frappe.db.get_value(
			"Loan Demand", {"loan": loan.name, "outstanding_amount": (">", 0)}, "outstanding_amount"
		)
		self.assertEqual(
			flt(outstanding_demand), 0, "There are still outstanding amounts in the loan demand."
		)

	def test_excess_amount_for_interest_waiver(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			"2024-07-15",
			"2024-06-25",
			rate_of_interest=10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-06-25", repayment_start_date="2024-07-15"
		)
		process_daily_loan_demands(posting_date="2025-01-05", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2025-01-16 00:06:10"), 100000, repayment_type="Principal Adjustment"
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2025-01-16 00:10:10"), 2600.00, repayment_type="Interest Waiver"
		)
		repayment_entry.submit()

		loan_status = frappe.db.get_value("Loan", loan.name, "status")
		self.assertEqual(loan_status, "Closed")

	def test_excess_amount_for_penal_waiver(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			2,
			"Customer",
			"2024-06-05",
			"2024-05-02",
			rate_of_interest=29,
			penalty_charges_rate=36,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-05-02", repayment_start_date="2024-06-05"
		)
		process_daily_loan_demands(posting_date="2024-07-07", loan=loan.name)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-07-07", company="_Test Company"
		)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2024-07-07")[
			"payable_amount"
		]

		first_normal_repayment = round(float(payable_amount), 2) - 2000  # partial payment

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2024-07-07 00:05:10"), first_normal_repayment
		)
		repayment_entry.submit()

		remaining_amount = calculate_amounts(against_loan=loan.name, posting_date="2024-07-07")[
			"payable_amount"
		]
		penalty_waiver = round(float(remaining_amount), 2) - 90  # checking excess_amount

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2024-07-07 00:06:10"), penalty_waiver, repayment_type="Penalty Waiver"
		)
		repayment_entry.submit()

		loan.load_from_db()
		self.assertEqual(loan.status, "Closed")

	def test_auto_waiver_after_auto_close_loan_for_penal(self):
		# This test verifies that when a normal repayment is made and the loan is auto-closed,
		# any remaining penal charges are waived automatically by creating a penalty waiver entry.

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			2,
			"Customer",
			"2024-06-05",
			"2024-05-02",
			rate_of_interest=29,
			penalty_charges_rate=36,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-05-02", repayment_start_date="2024-06-05"
		)
		process_daily_loan_demands(posting_date="2024-07-07", loan=loan.name)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-07-06", company="_Test Company"
		)

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2024-07-07")[
			"payable_amount"
		]

		repayment_entry_amount = payable_amount - 90

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2024-07-07 00:05:10"), repayment_entry_amount
		)
		repayment_entry.submit()

		auto_waiver_amount = payable_amount - repayment_entry.amount_paid

		loan_repayment_detail = frappe.db.get_value(
			"Loan Repayment",
			{"against_loan": loan.name, "repayment_type": "Penalty Waiver"},
			["repayment_type", "amount_paid"],
			order_by="creation desc",
			as_dict=1,
		)

		self.assertEqual(loan_repayment_detail.amount_paid, flt(auto_waiver_amount, 2))
		self.assertEqual(loan_repayment_detail.repayment_type, "Penalty Waiver")

	def test_auto_waiver_after_auto_close_loan_for_charges(self):
		# This test verifies that when a normal repayment is made and the loan is auto-closed,
		# any remaining charges are waived automatically by creating a charges waiver entry.

		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			"2024-07-15",
			"2024-06-25",
			10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-06-25", repayment_start_date="2024-07-15"
		)
		process_daily_loan_demands(posting_date="2024-12-15", loan=loan.name)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-12-14",
				"value_date": "2024-12-14",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 5000}],
			}
		)
		sales_invoice.submit()

		payable_amount = calculate_amounts(against_loan=loan.name, posting_date="2024-12-15")[
			"payable_amount"
		]

		repayment_entry_amount = payable_amount - 90

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2024-12-15 00:07:10"), repayment_entry_amount
		)
		repayment_entry.submit()

		auto_waiver_amount = payable_amount - repayment_entry.amount_paid

		loan_repayment_detail = frappe.db.get_value(
			"Loan Repayment",
			{"against_loan": loan.name},
			["repayment_type", "amount_paid"],
			order_by="creation desc",
			as_dict=1,
		)

		self.assertEqual(loan_repayment_detail.amount_paid, flt(auto_waiver_amount, 2))
		self.assertEqual(loan_repayment_detail.repayment_type, "Charges Waiver")

	def test_loan_restructure_schedule_with_bpi_adjustment(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2000000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			posting_date="2025-03-28",
			repayment_start_date="2025-04-28",
			rate_of_interest=31,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-03-22", repayment_start_date="2025-04-28"
		)

		repayment_entry_1 = create_repayment_entry(
			loan.name, get_datetime("2025-03-28 00:00:00"), 77.91, repayment_type="Pre Payment"
		)
		repayment_entry_1.submit()

		first_repay_schedule_current_principal_amount = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "status": "Active", "docstatus": 1},
			"current_principal_amount",
		)
		first_adjustment_after_pos = flt(loan.loan_amount - repayment_entry_1.amount_paid, 2)

		self.assertEqual(first_repay_schedule_current_principal_amount, first_adjustment_after_pos)

		process_daily_loan_demands(posting_date="2025-03-28", loan=loan.name)

		repayment_entry_2 = create_repayment_entry(
			loan.name, get_datetime("2025-03-28 01:00:00"), 5096.00, repayment_type="Pre Payment"
		)
		repayment_entry_2.submit()

		second_repay_schedule_current_principal_amount = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "status": "Active", "docstatus": 1},
			"current_principal_amount",
		)
		second_adjustment_after_pos = flt(
			first_repay_schedule_current_principal_amount - repayment_entry_2.amount_paid, 2
		)

		self.assertEqual(second_repay_schedule_current_principal_amount, second_adjustment_after_pos)

	def test_migrated_repayment_schedule(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			posting_date="2025-01-01",
			repayment_start_date="2025-01-05",
			rate_of_interest=10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-01-01", repayment_start_date="2025-01-05"
		)

		parent_schedule_name = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "status": "Active", "docstatus": 1}
		)

		payment_dates = [
			"2025-01-05",
			"2025-02-05",
			"2025-03-10",
			"2025-04-10",
			"2025-05-10",
			"2025-06-10",
		]

		rows = frappe.db.get_all(
			"Repayment Schedule",
			filters={"parent": parent_schedule_name},
			fields=["name"],
			order_by="idx asc",
		)

		for i, row in enumerate(rows):
			if i < len(payment_dates):
				frappe.db.set_value("Repayment Schedule", row.get("name"), "payment_date", payment_dates[i])

		process_daily_loan_demands(posting_date="2025-03-10", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2025-03-10", 51471)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2025-03-10", 15000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

		updated_rows = frappe.db.get_all(
			"Repayment Schedule",
			filters={"parent": parent_schedule_name},
			fields=["payment_date"],
			order_by="idx asc",
		)

		for i, row in enumerate(updated_rows):
			self.assertEqual(str(row.get("payment_date")), payment_dates[i])

	def test_charges_payment(self):
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

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

		# Create Charges Demand to simulate charge creation
		for i in range(0, 2):
			sales_invoice = create_sales_invoice(
				posting_date="2024-09-15", item_code="Processing Fee", qty=1, rate=1000, do_not_submit=1
			)
			sales_invoice.loan = loan.name
			sales_invoice.value_date = "2024-09-15"
			sales_invoice.save()
			sales_invoice.submit()

		repayment = create_repayment_entry(
			loan.name,
			"2024-09-15",
			1000,
			repayment_type="Charge Payment",
			payable_charges=[{"charge_code": "Processing Fee", "amount": 1000}],
		)
		repayment.submit()

		self.assertEqual(repayment.total_charges_paid, 1000)
		self.assertEqual(repayment.repayment_details[0].paid_amount, 1000)

		repayment = create_repayment_entry(
			loan.name,
			"2024-09-15",
			500,
			repayment_type="Charge Payment",
			payable_charges=[{"charge_code": "Processing Fee", "amount": 500}],
		)
		repayment.submit()

		self.assertEqual(repayment.total_charges_paid, 500)
		self.assertEqual(repayment.repayment_details[0].paid_amount, 500)

	def test_normal_loan_repayment_schedule_close(self):
		loan = create_loan(
			"_Test Customer 1",
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

		# Daily accrual
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-05", repayment_start_date="2024-04-05"
		)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2025-01-15",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 500}],
			}
		)
		sales_invoice.submit()

		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		repayment = create_repayment_entry(
			loan.name,
			"2024-04-05",
			104925,
		)

		repayment.submit()

		closed_schedule = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "docstatus": 1, "status": "Closed"},
			"name",
		)

		self.assertTrue(closed_schedule, "Repayment Schedule not closed")
		loan.load_from_db()

		# Loan will remain open because of pending charge
		self.assertEqual(loan.status, "Disbursed")

	def test_loc_loan_auto_waiver_demand_update(self):
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
			390547,
			disbursement_date="2024-10-30",
			repayment_start_date="2024-12-29",
			repayment_frequency="One Time",
		)
		disbursement.submit()

		process_daily_loan_demands(posting_date="2024-12-29 00:00:00", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-12-29 00:00:10", 401621, loan_disbursement=disbursement.name
		)

		repayment_entry.save()
		repayment_entry.submit()

		LoanDemand = DocType("Loan Demand")

		outstanding_demand = (
			frappe.qb.from_(LoanDemand)
			.select(fn.Sum(LoanDemand.outstanding_amount))
			.where((LoanDemand.loan == loan.name) & (LoanDemand.loan_disbursement == disbursement.name))
		).run()[0][0] or 0

		self.assertEqual(outstanding_demand, 0)

	def test_demand_reversal_on_invoice_cancel(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
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
				"posting_date": "2025-01-15",
				"posting_time": "00:06:10",
				"value_date": "2025-01-15",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 5000}],
			}
		)
		sales_invoice.submit()

		demand = frappe.db.get_value(
			"Loan Demand", {"sales_invoice": sales_invoice.name, "docstatus": 1}
		)
		self.assertTrue(demand, "Demand not created for Sales Invoice")
		demand = frappe.db.get_value(
			"Loan Demand", {"sales_invoice": sales_invoice.name, "docstatus": 2}
		)
		self.assertFalse(demand, "Demand should not be cancelled before Sales Invoice cancellation")

		sales_invoice.load_from_db()
		sales_invoice.cancel()

		demand = frappe.db.get_value(
			"Loan Demand", {"sales_invoice": sales_invoice.name, "docstatus": 2}
		)
		self.assertTrue(demand, "Demand not cancelled on Sales Invoice cancellation")

		demand = frappe.db.get_value(
			"Loan Demand", {"sales_invoice": sales_invoice.name, "docstatus": 1}
		)
		self.assertFalse(demand, "Demand should not be present after Sales Invoice cancellation")

	def test_loan_write_off_recovery_excess_amount(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)

		repayment = create_repayment_entry(
			loan.name, "2024-12-05", 10000000, repayment_type="Write Off Recovery"
		)
		repayment.submit()
		repayment.load_from_db()

		interest_waiver_amount = flt(
			frappe.db.get_value(
				"Loan Repayment",
				{"against_loan": loan.name, "repayment_type": "Interest Waiver", "docstatus": 1},
				"amount_paid",
			)
		)

		self.assertEqual(repayment.total_interest_paid, interest_waiver_amount)

		loan_status = frappe.db.get_value("Loan", loan.name, "status")
		self.assertEqual(loan_status, "Written Off")

		self.assertEqual(
			flt(repayment.excess_amount, 2),
			flt(repayment.amount_paid - repayment.pending_principal_amount - interest_waiver_amount, 2),
		)

	def test_loan_accounting_disabled(self):
		frappe.db.set_value("Company", "_Test Company", "enable_loan_accounting", 0)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
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

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2025-01-16")
		payable_amount = round(float(amounts["payable_amount"] or 0.0), 2)

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2025-01-16 00:03:10"), payable_amount
		)
		repayment_entry.submit()

		gl_entries = frappe.db.get_all(
			"GL Entry",
			filters={"against_voucher_type": "Loan", "against_voucher": loan.name},
		)

		self.assertEqual(len(gl_entries), 0)

	def test_mid_tenure_migrated_loan_import(self):
		disb_id = f"DISB-MID-{random_string(5).upper()}"
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			applicant_type="Customer",
			repayment_start_date="2024-02-15",
			posting_date="2024-01-15",
			rate_of_interest=12.5,
			penalty_charges_rate=2,
			repayment_frequency="Monthly",
			migration_date="2024-06-15",
			is_imported=1,
			loan_import_details=[{
				"disbursed_amount": 500000,
				"disbursement_date": "2024-01-15",
				"loan_disbursement_id": disb_id,
				"opening_additional_outstanding": 1500,
				"opening_charge_outstanding": 800,
				"opening_interest_outstanding": 28500,
				"opening_principal_outstanding": 375000,
				"opening_penalty_outstanding": 3200,
			}],
		)

		loan.submit()

		loan.load_from_db()

		self.assertTrue(frappe.db.exists("Loan", {"name": loan.name}))
		self.assertTrue(frappe.db.exists("Loan Disbursement", {"against_loan": loan.name, "is_imported": 1}))
		self.assertTrue(frappe.db.exists("Loan Interest Accrual", {"loan": loan.name, "is_imported": 1}))
		self.assertTrue(frappe.db.exists("Loan Demand", {"loan": loan.name, "is_imported": 1}))

	def test_closed_migrated_loan_import(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			applicant_type="Customer",
			repayment_start_date="2024-02-15",
			posting_date="2024-01-15",
			rate_of_interest=10,
			penalty_charges_rate=2,
			repayment_frequency="Monthly",
			migration_date="2025-10-31",
			is_imported=1,
			status="Closed",
		)

		loan.submit()

		loan.load_from_db()

		self.assertTrue(frappe.db.exists("Loan", {"name": loan.name}))
		self.assertFalse(frappe.db.exists("Loan Disbursement", {"against_loan": loan.name, "is_imported": 1}))
		self.assertFalse(frappe.db.exists("Loan Interest Accrual", {"loan": loan.name, "is_imported": 1}))
		self.assertFalse(frappe.db.exists("Loan Demand", {"loan": loan.name, "is_imported": 1}))

	def test_cancel_loan_cancels_process_loan_documents(self):
		posting_date = "2025-01-30"
		loan = create_loan(
			self.applicant2,
			"Term Loan Product 1",
			12000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date=posting_date,
			posting_date=add_months(posting_date, -1),
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=add_months(posting_date, -1),
			repayment_start_date=posting_date,
		)
		process_loan_interest_accrual_for_loans(
			posting_date=posting_date, loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date=posting_date, loan=loan.name)

		process_doctypes = ["Process Loan Demand", "Process Loan Interest Accrual"]

		for doctype in process_doctypes:
			self.assertTrue(
				frappe.db.exists(doctype, {"loan": loan.name, "docstatus": 1}),
				msg=f"Expected a submitted {doctype} for the loan",
			)

		for demand in frappe.get_all("Loan Demand", filters={"loan": loan.name, "docstatus": 1}, pluck="name"):
			frappe.get_doc("Loan Demand", demand).cancel()
		for accrual in frappe.get_all(
			"Loan Interest Accrual", filters={"loan": loan.name, "docstatus": 1}, pluck="name"
		):
			frappe.get_doc("Loan Interest Accrual", accrual).cancel()
		for disbursement in frappe.get_all(
			"Loan Disbursement", filters={"against_loan": loan.name, "docstatus": 1}, pluck="name"
		):
			frappe.get_doc("Loan Disbursement", disbursement).cancel()

		loan.load_from_db()
		loan.cancel()

		for doctype in process_doctypes:
			self.assertFalse(
				frappe.db.exists(doctype, {"loan": loan.name, "docstatus": 1}),
				msg=f"{doctype} left in Submitted state after loan cancellation",
			)

		for doctype, fieldname in (
			("Loan Demand", "loan"),
			("Loan Interest Accrual", "loan"),
			("Loan Disbursement", "against_loan"),
			("Loan Repayment Schedule", "loan"),
		):
			for name in frappe.get_all(doctype, filters={fieldname: loan.name}, pluck="name"):
				frappe.delete_doc(doctype, name, force=True)

		frappe.db.set_single_value("Accounts Settings", "delete_linked_ledger_entries", 1)
		try:
			frappe.delete_doc("Loan", loan.name)
		finally:
			frappe.db.set_single_value("Accounts Settings", "delete_linked_ledger_entries", 0)
		self.assertFalse(frappe.db.exists("Loan", loan.name))
