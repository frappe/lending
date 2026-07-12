# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import get_last_day

from lending.loan_management.doctype.process_consolidated_loan_gl.process_consolidated_loan_gl import (
	run_consolidation_for_loan,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_loan,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)
from lending.tests.utils import LendingTestSuite

COMPANY = "_Test Company"


class TestProcessConsolidatedLoanGL(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		set_loan_accrual_frequency("Daily")

	def tearDown(self):
		frappe.db.set_value(
			"Company",
			COMPANY,
			{"loan_gl_consolidation": 0, "loan_gl_consolidation_start_date": None},
			update_modified=False,
		)

	def enable_consolidation(self, start_date):
		frappe.db.set_value(
			"Company",
			COMPANY,
			{"loan_gl_consolidation": 1, "loan_gl_consolidation_start_date": start_date},
			update_modified=False,
		)

	def gl_count(self, voucher_no):
		return frappe.db.count(
			"GL Entry", {"voucher_no": voucher_no, "is_cancelled": 0}
		)

	def consolidated_income(self, loan):
		"""Net income (credit - debit on income accounts) booked via consolidated vouchers."""
		val = frappe.db.sql(
			"""select sum(credit) - sum(debit) from `tabGL Entry`
			where against_voucher=%s and voucher_type='Process Consolidated Loan GL'
				and account like '%%Income%%' and is_cancelled=0""",
			loan,
		)[0][0]
		return round(val or 0, 2)

	def make_loan_with_daily_accruals(self, posting_date, till_date):
		loan = create_loan(
			self.applicant,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=get_last_day(posting_date),
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			1000000,
			disbursement_date=posting_date,
			repayment_start_date=get_last_day(posting_date),
		)
		process_loan_interest_accrual_for_loans(
			posting_date=till_date, loan=loan.name, company=COMPANY
		)
		return loan.name

	def test_daily_accruals_are_deferred_and_consolidated(self):
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-25")

		accruals = frappe.get_all(
			"Loan Interest Accrual", {"loan": loan, "docstatus": 1}, ["name", "gl_posted"]
		)
		self.assertTrue(len(accruals) > 1, "expected multiple daily accruals")
		self.assertTrue(all(a.gl_posted == 0 for a in accruals), "all daily GL deferred")
		for a in accruals:
			self.assertEqual(self.gl_count(a.name), 0, "deferred accrual posts no GL of its own")

		voucher = run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		self.assertTrue(voucher)

		# voucher is scoped to this loan and carries the consolidated GL
		self.assertEqual(frappe.db.get_value("Process Consolidated Loan GL", voucher, "loan"), loan)
		self.assertTrue(self.gl_count(voucher) > 0)

		# a breakdown table explains what was rolled up
		details = frappe.get_all(
			"Consolidated Loan GL Detail",
			{"parent": voucher},
			["source_type", "account", "source_doc_count"],
		)
		self.assertTrue(details, "consolidation_details should be populated")
		self.assertTrue(all(d.source_doc_count > 0 for d in details))

		# all accruals flagged posted and linked to the voucher
		accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1},
			["gl_posted", "consolidated_gl_voucher"],
		)
		self.assertTrue(all(a.gl_posted == 1 for a in accruals))
		self.assertTrue(all(a.consolidated_gl_voucher == voucher for a in accruals))

	def test_consolidation_is_idempotent(self):
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")

		v1 = run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		self.assertTrue(self.gl_count(v1) > 0)
		income_after_first = self.consolidated_income(loan)

		# second run, nothing new deferred -> no GL, income unchanged
		v2 = run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		self.assertEqual(self.gl_count(v2), 0)
		self.assertEqual(self.consolidated_income(loan), income_after_first)

	def test_mid_month_cancel_reverses_via_delta(self):
		"""Cancelling a consolidated accrual mid-month posts a reversing delta backing out its amount."""
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")

		run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		income_before = self.consolidated_income(loan)
		self.assertGreater(income_before, 0)

		acc = frappe.db.get_value(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1, "gl_posted": 1, "interest_amount": [">", 0]},
			"name",
		)
		interest = frappe.db.get_value("Loan Interest Accrual", acc, "interest_amount")
		frappe.get_doc("Loan Interest Accrual", acc).cancel()

		run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		# income drops by exactly the cancelled accrual amount
		self.assertAlmostEqual(income_before - self.consolidated_income(loan), interest, places=2)

		# re-running with nothing changed is stable (no double reversal)
		income_after = self.consolidated_income(loan)
		run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		self.assertEqual(self.consolidated_income(loan), income_after)

	def test_disabled_company_posts_daily_gl(self):
		"""Consolidation off -> unchanged daily behaviour."""
		posting_date = "2024-04-05"
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")

		accruals = frappe.get_all(
			"Loan Interest Accrual", {"loan": loan, "docstatus": 1}, ["name", "gl_posted"]
		)
		self.assertTrue(all(a.gl_posted == 1 for a in accruals))
		posted = sum(self.gl_count(a.name) for a in accruals)
		self.assertTrue(posted > 0, "daily GL should be posted when consolidation is off")
