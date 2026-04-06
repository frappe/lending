# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from collections import Counter

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Sum
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, date_diff, flt, getdate

from erpnext.selling.doctype.customer.test_customer import get_customer_dict

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
	create_process_loan_classification,
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
	loan_classification_ranges,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)


class TestLoanRestructure(IntegrationTestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		loan_classification_ranges()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_loan_restructure_capitalization(self):
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
			penalty_charges_rate=36,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-02-20", repayment_start_date="2024-04-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-04-04", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2024-04-05")

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2024-04-10")

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-02-20",
				"value_date": "2024-02-20",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 5000}],
				"debit_to": "Processing Fee Receivable Account - _TC",
			}
		)
		sales_invoice.submit()

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-02-20",
				"value_date": "2024-02-20",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Documentation Charge", "qty": 1, "rate": 1000}],
			}
		)
		sales_invoice.submit()

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2024-04-11",
			interest_waiver_amount=500,
			penal_waiver_amount=10,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		repayments = frappe.db.get_all(
			"Loan Repayment",
			filters={"loan_restructure": loan_restructure.name, "docstatus": 1},
			pluck="name",
		)

		self.assertEqual(len(repayments), 8)

	def test_clears_principal_overdue_demands_on_normal_restructure(self):
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
			penalty_charges_rate=36,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-02-20", repayment_start_date="2024-04-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-04-04", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2024-04-05")

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2024-04-10")

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2024-04-11",
			interest_waiver_amount=500,
			penal_waiver_amount=10,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		LoanDemand = DocType("Loan Demand")

		total_outstanding = (
			frappe.qb.from_(LoanDemand)
			.select(Sum(LoanDemand.outstanding_amount))
			.where(LoanDemand.loan == loan.name)
			.where(LoanDemand.demand_type == "EMI")
			.where(LoanDemand.demand_subtype == "Principal")
			.where(LoanDemand.docstatus == 1)
		).run()[0][0]

		self.assertEqual(flt(total_outstanding), 0)

	def test_loan_restructure_charges_waiver_and_capitalization(self):
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

		process_daily_loan_demands(loan=loan.name, posting_date="2024-04-05")

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-02-20",
				"value_date": "2024-02-20",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"debit_to": "Processing Fee Receivable Account - _TC",
				"items":
				[
					{"item_code": "Processing Fee", "qty": 1, "rate": 4000},
					{"item_code": "Documentation Charge", "qty": 1, "rate": 3000},
				],
			}
		)
		sales_invoice.submit()

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2024-02-20",
				"value_date": "2024-02-20",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 2000}],
			}
		)
		sales_invoice.submit()

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2024-04-11",
			interest_waiver_amount=500,
			loan_restructure_charges=[
				{"charge": "Processing Fee", "capitalize_amount": 6000, "treatment_of_other_charges": "Capitalize"},
				{"charge": "Documentation Charge", "capitalize_amount": 2500, "treatment_of_other_charges": "Capitalize"},
			],
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		repayments = frappe.db.get_all(
			"Loan Repayment",
			filters={"loan_restructure": loan_restructure.name, "docstatus": 1},
			pluck="repayment_type",
		)

		self.assertEqual(len(repayments), 7)

		counts = Counter(repayments)

		self.assertEqual(counts.get("Charges Capitalization", 0), 2)
		self.assertEqual(counts.get("Charges Waiver", 0), 1)

	def test_unaccrued_interest_capitalization_gl_entries(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2300000,
			"Repay Over Number of Periods",
			24,
			repayment_start_date="2025-11-05",
			posting_date="2025-10-09",
			rate_of_interest=27,
			applicant_type="Customer",
			penalty_charges_rate=36,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-10-09", repayment_start_date="2025-11-05"
		)

		process_loan_interest_accrual_for_loans(posting_date="2025-12-04", loan=loan.name, company="_Test Company")
		process_daily_loan_demands(loan=loan.name, posting_date="2026-01-05")
		process_loan_interest_accrual_for_loans(posting_date="2026-02-03", loan=loan.name, company="_Test Company")

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-02-04",
			interest_waiver_amount=1001,
			unaccrued_interest_waiver=1004,
			penal_waiver_amount=1002,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan_repayment = frappe.db.get_value(
			"Loan Repayment",
			{
				"loan_restructure": loan_restructure.name,
				"docstatus": 1,
				"repayment_type": "Interest Capitalization",
				"unbooked_interest_paid": (">", 0),
			},
			["name", "unbooked_interest_paid"],
			as_dict=True,
		)

		amount = flt(loan_repayment.unbooked_interest_paid, 2)

		gl_entries = frappe.db.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Loan Repayment",
				"voucher_no": loan_repayment.name,
				"is_cancelled": 0,
			},
			fields=["account", "debit", "credit"],
		)

		expected_entries = [
			{"account": "Loan Account - _TC", "debit": amount, "credit": 0.0},
			{"account": "Interest Receivable - _TC", "debit": 0.0, "credit": amount},
		]

		for expected in expected_entries:
			self.assertIn(expected, gl_entries, f"Missing GL entry: {expected}")

	def test_normal_restructure_first_emi_schedule_days(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			1200000,
			"Repay Over Number of Periods",
			36,
			repayment_start_date="2025-10-05",
			posting_date="2024-09-19",
			rate_of_interest=24,
			applicant_type="Customer",
			penalty_charges_rate=36,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-09-19", repayment_start_date="2025-10-05"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-01-05")

		restructure_date = "2026-02-02"
		repayment_start_date = "2026-02-05"

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date=restructure_date,
			repayment_start_date=repayment_start_date
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "loan_restructure": loan_restructure.name}
		)

		date_diff_value = date_diff(repayment_start_date, restructure_date)
		number_of_days_for_first_emi = loan_repayment_schedule.repayment_schedule[0].number_of_days

		self.assertEqual(date_diff_value, number_of_days_for_first_emi)

	def test_non_npa_restructure_resets_dpd_without_watch_period(self):
		"""
		Verify that restructuring a non-NPA loan resets DPD to zero
		without setting any watch period or NPA tagging.
		"""
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

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
			posting_date="2024-04-04", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2024-04-05")
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2024-04-10")
		create_process_loan_classification(posting_date="2024-04-11", loan=loan.name)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2024-04-11",
			repayment_start_date="2024-05-11",
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan.load_from_db()
		self.assertFalse(loan.watch_period_end_date)
		self.assertEqual(loan.days_past_due, 0)
		self.assertEqual(loan.is_npa, 0)

		process_daily_loan_demands(loan=loan.name, posting_date="2024-08-11")
		create_process_loan_classification(posting_date="2024-08-11", loan=loan.name, force_update_dpd_in_loan=1)

		loan.load_from_db()
		self.assertEqual(loan.is_npa, 1)
		watch_period_days = frappe.db.get_value(
			"Company", "_Test Company", "watch_period_post_loan_restructure_in_days"
		)
		watch_period_end_date = add_days("2024-08-11", watch_period_days)

		self.assertEqual(loan.watch_period_end_date, getdate(watch_period_end_date))

	def test_npa_restructure_keeps_classification_same(self):
		"""
		Verify that after restructuring an NPA loan,
		the loan classification stays the same during the watch period.
		"""

		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		customer = frappe.get_doc(get_customer_dict("NPA Restructure 1")).insert()
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan = create_loan(
			customer.name,
			"Term Loan Product 4",
			2300000.00,
			"Repay Over Number of Periods",
			24,
			repayment_start_date="2025-10-05",
			posting_date="2025-09-13",
			rate_of_interest=27,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2025-09-13", repayment_start_date="2025-10-05"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-02-05")

		process_loan_interest_accrual_for_loans(
			posting_date="2026-02-18", loan=loan.name, company="_Test Company"
		)

		create_process_loan_classification(posting_date="2026-02-18", loan=loan.name, force_update_dpd_in_loan=1)

		loan.load_from_db()
		classification_code = loan.classification_code

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-02-18",
			repayment_start_date="2026-03-05",
			interest_waiver_amount=1001,
			unaccrued_interest_waiver=1002,
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan.load_from_db()
		self.assertTrue(loan.watch_period_end_date)
		self.assertEqual(loan.days_past_due, 0)
		self.assertEqual(loan.is_npa, 1)
		self.assertEqual(loan.classification_code, classification_code)

	def test_npa_restructure_watch_period_resets_on_dpd(self):
		"""
		Verify that when DPD increases after NPA restructuring,
		the watch period is reset from the new DPD date.
		"""

		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		customer = frappe.get_doc(get_customer_dict("NPA Restructure 1")).insert()
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan = create_loan(
			customer.name,
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

		process_daily_loan_demands(loan=loan.name, posting_date="2024-08-05")

		create_process_loan_classification(posting_date="2024-08-05", loan=loan.name, force_update_dpd_in_loan=1)

		loan.load_from_db()
		classification_code = loan.classification_code

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2024-08-06",
			repayment_start_date="2024-09-05",
		)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		loan.load_from_db()
		self.assertTrue(loan.watch_period_end_date)
		self.assertEqual(loan.days_past_due, 0)
		self.assertEqual(loan.is_npa, 1)
		self.assertEqual(loan.classification_code, classification_code)

		process_daily_loan_demands(loan=loan.name, posting_date="2024-09-05")
		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-09-05")
		payable_amount = round(float(amounts["payable_amount"] or 0.0), 2)

		repayment_entry = create_repayment_entry(loan.name, "2024-09-05", payable_amount)
		repayment_entry.submit()

		process_daily_loan_demands(loan=loan.name, posting_date="2024-10-05")
		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-10-05")
		payable_amount = round(float(amounts["payable_amount"] or 0.0), 2)

		repayment_entry = create_repayment_entry(loan.name, "2024-10-05", payable_amount)
		repayment_entry.submit()

		process_daily_loan_demands(loan=loan.name, posting_date="2024-11-05")
		create_process_loan_classification(posting_date="2024-11-05", loan=loan.name, force_update_dpd_in_loan=1)
		loan.load_from_db()
		watch_period_days = frappe.db.get_value(
			"Company", "_Test Company", "watch_period_post_loan_restructure_in_days"
		)
		watch_period_end_date = add_days("2024-11-05", watch_period_days)

		self.assertEqual(loan.watch_period_end_date, getdate(watch_period_end_date))


def create_loan_restructure(
	loan,
	restructure_date,
	repayment_start_date=None,
	interest_waiver_amount=None,
	unaccrued_interest_waiver=None,
	penal_waiver_amount=None,
	treatment_of_normal_interest="Capitalize",
	unaccrued_interest_treatment="Capitalize",
	treatment_of_penal_interest="Capitalize",
	loan_restructure_charges=None,
):

	doc = frappe.new_doc("Loan Restructure")
	doc.loan = loan
	doc.restructure_date = restructure_date
	doc.repayment_start_date = repayment_start_date or restructure_date
	doc.interest_waiver_amount = interest_waiver_amount
	doc.unaccrued_interest_waiver = unaccrued_interest_waiver
	doc.penal_interest_waiver = penal_waiver_amount
	doc.restructure_type = "Normal Restructure"
	doc.treatment_of_normal_interest = treatment_of_normal_interest
	doc.unaccrued_interest_treatment = unaccrued_interest_treatment
	doc.treatment_of_penal_interest = treatment_of_penal_interest

	if loan_restructure_charges:
		for charge in loan_restructure_charges:
			doc.append(
				"loan_restructure_charges",
				{
					"charge": charge.get("charge"),
					"capitalize_amount": charge.get("capitalize_amount"),
					"treatment_of_other_charges": charge.get("treatment_of_other_charges"),
				},
			)

	doc.submit()

	return doc
