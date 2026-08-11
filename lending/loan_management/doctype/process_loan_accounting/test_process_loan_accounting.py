# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_months, flt, get_last_day, getdate

from lending.loan_management.doctype.loan_repayment_repost.loan_repayment_repost import (
	reconsolidate_gl_for_loan,
)
from lending.loan_management.doctype.process_loan_accounting.process_loan_accounting import (
	completed_month_ends,
	run_consolidation_for_loan,
)
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
	create_loan_partner,
	create_loan_write_off,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)
from lending.tests.utils import LendingTestSuite

COMPANY = "_Test Company"


class TestProcessLoanAccounting(LendingTestSuite):
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
			where against_voucher=%s and voucher_type='Process Loan Accounting'
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
			"Loan Interest Accrual", {"loan": loan, "docstatus": 1}, ["name", "process_loan_accounting_voucher"]
		)
		self.assertTrue(len(accruals) > 1, "expected multiple daily accruals")
		self.assertTrue(all(not a.process_loan_accounting_voucher for a in accruals), "all daily GL deferred")
		for a in accruals:
			self.assertEqual(self.gl_count(a.name), 0, "deferred accrual posts no GL of its own")

		voucher = run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		self.assertTrue(voucher)

		self.assertEqual(frappe.db.get_value("Process Loan Accounting", voucher, "loan"), loan)
		self.assertTrue(self.gl_count(voucher) > 0)

		details = frappe.get_all(
			"Process Loan Accounting Detail",
			{"parent": voucher},
			["source_type", "source_document", "account", "debit", "credit", "source_doc_count"],
		)
		self.assertTrue(details, "consolidation_details should be populated")
		self.assertTrue(all(d.source_doc_count > 0 for d in details))

		for d in details:
			if d.source_doc_count == 1:
				self.assertTrue(d.source_document, "single-doc line should link its source")
				self.assertTrue(
					frappe.db.exists(d.source_type, d.source_document),
					"linked source document must exist and match its type",
				)
			else:
				self.assertFalse(d.source_document, "merged line must not link one document")

		detail_debit = sum(flt(d.debit) for d in details)
		detail_credit = sum(flt(d.credit) for d in details)
		gl_totals = frappe.db.sql(
			"select sum(debit), sum(credit) from `tabGL Entry` where voucher_no=%s and is_cancelled=0",
			voucher,
		)[0]
		self.assertAlmostEqual(detail_debit, flt(gl_totals[0]), places=2)
		self.assertAlmostEqual(detail_credit, flt(gl_totals[1]), places=2)
		self.assertAlmostEqual(detail_debit, detail_credit, places=2)

		accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1},
			["process_loan_accounting_voucher"],
		)
		self.assertTrue(all(a.process_loan_accounting_voucher == voucher for a in accruals))

	def test_consolidation_is_idempotent(self):
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")

		v1 = run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		self.assertTrue(self.gl_count(v1) > 0)
		income_after_first = self.consolidated_income(loan)

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
			{
				"loan": loan,
				"docstatus": 1,
				"process_loan_accounting_voucher": ["is", "set"],
				"interest_amount": [">", 0],
			},
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

	def test_cancelling_delta_voucher_reopens_its_reversal(self):
		"""Cancelling the delta voucher that reversed a cancelled accrual must not strand the ledger.

		V0 consolidates the accrual. The accrual is cancelled, so V1's delta reverses it (income
		drops). If V1 is itself cancelled, its own reversal GL cancels out that delta (income is
		back up), but the accrual must still be picked up by the next run so its GL nets to zero
		again -- it must not become invisible to both the pending and reversal-pending queries.
		"""
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")

		run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		income_before = self.consolidated_income(loan)

		acc = frappe.db.get_value(
			"Loan Interest Accrual",
			{
				"loan": loan,
				"docstatus": 1,
				"process_loan_accounting_voucher": ["is", "set"],
				"interest_amount": [">", 0],
			},
			"name",
		)
		frappe.get_doc("Loan Interest Accrual", acc).cancel()

		v1 = run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		income_after_delta = self.consolidated_income(loan)
		self.assertLess(income_after_delta, income_before)

		frappe.get_doc("Process Loan Accounting", v1).cancel()

		# V1's own reversal undoes its delta, so income is back to the pre-cancel amount.
		self.assertEqual(self.consolidated_income(loan), income_before)
		self.assertEqual(
			frappe.db.get_value("Loan Interest Accrual", acc, "process_loan_accounting_voucher"),
			v1,
			"accrual must be reversal-pending again, not stranded with a null voucher link",
		)

		run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)

		# the reversal is reapplied, settling back to the same net income as before V1 was cancelled
		self.assertEqual(self.consolidated_income(loan), income_after_delta)

	def test_disabled_company_posts_daily_gl(self):
		"""Consolidation off -> unchanged daily behaviour."""
		posting_date = "2024-04-05"
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")

		accruals = frappe.get_all(
			"Loan Interest Accrual", {"loan": loan, "docstatus": 1}, ["name", "process_loan_accounting_voucher"]
		)
		self.assertTrue(all(not a.process_loan_accounting_voucher for a in accruals))
		posted = sum(self.gl_count(a.name) for a in accruals)
		self.assertTrue(posted > 0, "daily GL should be posted when consolidation is off")

	def test_npa_suspense_je_consolidated(self):
		"""NPA suspense JE is deferred per-accrual and consolidated to one JE per loan/month.

		Invariant: each month's consolidated suspense JE equals the sum of that month's live NPA
		accrual interest, with no duplicate JEs and a balanced ledger.
		"""
		from frappe.utils import get_first_day

		start = "2024-04-01"
		self.enable_consolidation(start)
		frappe.db.set_value(
			"Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90
		)

		loan = create_loan(
			self.applicant,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			applicant_type="Customer",
			repayment_start_date="2024-04-05",
			posting_date="2024-03-05",
			rate_of_interest=8.5,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-05", repayment_start_date="2024-04-05"
		)
		for d in ["2024-04-30", "2024-05-31", "2024-06-30", "2024-07-31"]:
			process_daily_loan_demands(posting_date=d, loan=loan.name)
			process_loan_interest_accrual_for_loans(posting_date=d, loan=loan.name)
		create_process_loan_classification(
			posting_date="2024-08-05", loan=loan.name, force_update_dpd_in_loan=1
		)
		for d in ["2024-08-31", "2024-09-30"]:
			process_loan_interest_accrual_for_loans(posting_date=d, loan=loan.name)

		self.assertEqual(
			frappe.db.count(
				"Loan Interest Accrual",
				{"loan": loan.name, "docstatus": 1, "normal_interest_journal_entry": ["is", "set"]},
			),
			0,
			"per-accrual suspense JE should be deferred under consolidation",
		)

		for me in ["2024-08-31", "2024-09-30"]:
			run_consolidation_for_loan(loan.name, me, force=True)

		tags = frappe.get_all(
			"Journal Entry",
			{"loan": loan.name, "process_loan_accounting_month_end": ["is", "set"], "docstatus": 1},
			["name", "process_loan_accounting_month_end"],
		)
		self.assertTrue(tags, "consolidated suspense JEs should exist for NPA months")
		seen = set()
		for je in tags:
			self.assertNotIn(je.process_loan_accounting_month_end, seen, "no duplicate suspense JE per month")
			seen.add(je.process_loan_accounting_month_end)
			month_end = je.process_loan_accounting_month_end
			je_credit = frappe.db.sql(
				"""select sum(credit) - sum(debit) from `tabGL Entry`
				where voucher_no=%s and account like '%%uspense%%' and is_cancelled=0""",
				je.name,
			)[0][0] or 0
			live = frappe.db.sql(
				"""select sum(interest_amount) from `tabLoan Interest Accrual`
				where loan=%s and docstatus=1 and is_npa=1 and unmark_npa=0
					and posting_date between %s and %s""",
				(loan.name, get_first_day(month_end), month_end),
			)[0][0] or 0
			self.assertAlmostEqual(je_credit, live, places=2)

		net = frappe.db.sql(
			"select sum(debit) - sum(credit) from `tabGL Entry` where against_voucher=%s and is_cancelled=0",
			loan.name,
		)[0][0] or 0
		self.assertAlmostEqual(net, 0, places=2)

	def test_non_npa_loan_has_no_suspense_je(self):
		"""A loan that never goes NPA should not get a consolidated suspense JE."""
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-25")

		run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)

		self.assertEqual(
			frappe.db.count(
				"Journal Entry",
				{"loan": loan, "process_loan_accounting_month_end": ["is", "set"], "docstatus": 1},
			),
			0,
			"non-NPA loan should not get a consolidated suspense JE",
		)

	def test_written_off_loan_posts_no_gl_after_write_off(self):
		"""Accruals dated on/after the write-off date carry no GL, so consolidation for that
		month posts nothing for them (existing write-off guard in build_gl_map is preserved)."""
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")

		create_loan_write_off(loan, "2024-04-15")

		# accrue further after the write-off date
		process_loan_interest_accrual_for_loans(posting_date="2024-04-20", loan=loan, company=COMPANY)

		voucher = run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)

		post_write_off_accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1, "posting_date": [">=", "2024-04-15"]},
			pluck="name",
		)
		self.assertTrue(post_write_off_accruals, "expected accruals dated on/after write-off")
		for a in post_write_off_accruals:
			self.assertEqual(self.gl_count(a), 0, "no GL for accruals on/after write-off date")

		if voucher:
			detail_docs = frappe.get_all(
				"Process Loan Accounting Detail", {"parent": voucher, "source_type": "Loan Interest Accrual"},
				pluck="source_document",
			)
			self.assertFalse(
				set(detail_docs) & set(post_write_off_accruals),
				"post-write-off accruals must not appear in the consolidated breakdown",
			)

	def test_async_gl_reversal_ignored_when_consolidation_enabled(self):
		"""Consolidation takes priority over async_gl_reversal: cancelling a deferred accrual still
		nets out via the next consolidation run, not via a queued async reversal."""
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		frappe.db.set_value(
			"Company",
			COMPANY,
			{"enable_async_gl_reversal": 1, "async_gl_reversal_start_date": posting_date},
			update_modified=False,
		)
		self.addCleanup(
			frappe.db.set_value,
			"Company",
			COMPANY,
			{"enable_async_gl_reversal": 0, "async_gl_reversal_start_date": None},
			update_modified=False,
		)

		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")
		run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		income_before = self.consolidated_income(loan)

		acc = frappe.db.get_value(
			"Loan Interest Accrual",
			{
				"loan": loan,
				"docstatus": 1,
				"process_loan_accounting_voucher": ["is", "set"],
				"interest_amount": [">", 0],
			},
			"name",
		)
		interest = frappe.db.get_value("Loan Interest Accrual", acc, "interest_amount")
		doc = frappe.get_doc("Loan Interest Accrual", acc)
		# cancel runs synchronously here regardless of async_gl_reversal, since make_gl_entries
		# defers to consolidation before queue_cancel_gl is ever consulted.
		doc.cancel()
		self.assertEqual(self.gl_count(acc), 0, "cancel should not post its own reversal GL")

		run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		self.assertAlmostEqual(income_before - self.consolidated_income(loan), interest, places=2)

	def test_immutable_ledger_on_reverses_with_forward_entry(self):
		"""With immutable ledger on, cancelling a consolidated voucher leaves the original rows
		untouched (is_cancelled stays 0) and adds a fresh forward-dated reversing entry, instead of
		marking the original rows cancelled."""
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)
		frappe.db.set_single_value("Accounts Settings", "enable_immutable_ledger", 1)
		self.addCleanup(
			frappe.db.set_single_value, "Accounts Settings", "enable_immutable_ledger", 0
		)

		loan = self.make_loan_with_daily_accruals(posting_date, "2024-04-15")
		voucher = run_consolidation_for_loan(loan, get_last_day(posting_date), force=True)
		self.assertTrue(voucher)

		original_rows = frappe.get_all(
			"GL Entry", {"voucher_no": voucher, "is_cancelled": 0}, ["name", "debit", "credit"]
		)
		self.assertTrue(original_rows)
		original_row_count = len(original_rows)

		frappe.get_doc("Process Loan Accounting", voucher).cancel()

		for row in original_rows:
			gl = frappe.db.get_value("GL Entry", row.name, ["is_cancelled", "debit", "credit"], as_dict=True)
			self.assertEqual(gl.is_cancelled, 0)
			self.assertAlmostEqual(flt(gl.debit), flt(row.debit), places=2)
			self.assertAlmostEqual(flt(gl.credit), flt(row.credit), places=2)

		live_rows = frappe.get_all("GL Entry", {"voucher_no": voucher, "is_cancelled": 0})
		self.assertEqual(len(live_rows), original_row_count * 2)

		net = frappe.db.sql(
			"select sum(debit) - sum(credit) from `tabGL Entry` where against_voucher=%s and is_cancelled=0",
			loan,
		)[0][0] or 0
		self.assertAlmostEqual(net, 0, places=2)

	def test_npa_repost_mid_month_cancel_settles_correctly(self):
		"""Reposting a loan that has already gone NPA, with a mid-month cancellation folded in,
		still leaves the consolidated suspense JE equal to the live NPA interest for the month."""
		from frappe.utils import get_first_day

		start = "2024-04-01"
		self.enable_consolidation(start)
		frappe.db.set_value(
			"Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90
		)

		loan = create_loan(
			self.applicant,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			applicant_type="Customer",
			repayment_start_date="2024-04-05",
			posting_date="2024-03-05",
			rate_of_interest=8.5,
		)
		loan.submit()
		disbursement = make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-05", repayment_start_date="2024-04-05"
		)
		for d in ["2024-04-30", "2024-05-31", "2024-06-30", "2024-07-31"]:
			process_daily_loan_demands(posting_date=d, loan=loan.name)
			process_loan_interest_accrual_for_loans(posting_date=d, loan=loan.name)
		create_process_loan_classification(
			posting_date="2024-08-05", loan=loan.name, force_update_dpd_in_loan=1
		)
		for d in ["2024-08-31", "2024-09-30"]:
			process_loan_interest_accrual_for_loans(posting_date=d, loan=loan.name)
			run_consolidation_for_loan(loan.name, d, force=True)

		# repost from mid-NPA-period; cancels and regenerates accruals/demands from that date
		frappe.get_doc(
			{
				"doctype": "Loan Repayment Repost",
				"loan": loan.name,
				"loan_disbursement": disbursement.name,
				"repost_date": "2024-08-15",
				"cancel_future_emi_demands": 1,
				"cancel_future_accruals_and_demands": 1,
			}
		).submit()

		for me in ["2024-08-31", "2024-09-30"]:
			run_consolidation_for_loan(loan.name, me, force=True)

		tags = frappe.get_all(
			"Journal Entry",
			{"loan": loan.name, "process_loan_accounting_month_end": ["is", "set"], "docstatus": 1},
			["name", "process_loan_accounting_month_end"],
		)
		self.assertTrue(tags, "consolidated suspense JEs should exist after repost")
		seen = set()
		for je in tags:
			self.assertNotIn(je.process_loan_accounting_month_end, seen, "no duplicate suspense JE per month after repost")
			seen.add(je.process_loan_accounting_month_end)
			month_end = je.process_loan_accounting_month_end
			je_credit = frappe.db.sql(
				"""select sum(credit) - sum(debit) from `tabGL Entry`
				where voucher_no=%s and account like '%%uspense%%' and is_cancelled=0""",
				je.name,
			)[0][0] or 0
			live = frappe.db.sql(
				"""select sum(interest_amount) from `tabLoan Interest Accrual`
				where loan=%s and docstatus=1 and is_npa=1 and unmark_npa=0
					and posting_date between %s and %s""",
				(loan.name, get_first_day(month_end), month_end),
			)[0][0] or 0
			self.assertAlmostEqual(je_credit, live, places=2)

		net = frappe.db.sql(
			"select sum(debit) - sum(credit) from `tabGL Entry` where against_voucher=%s and is_cancelled=0",
			loan.name,
		)[0][0] or 0
		self.assertAlmostEqual(net, 0, places=2)

	def test_loc_loan_with_multiple_disbursements_consolidates_correctly(self):
		"""LOC loans track accruals per disbursement. Consolidation should still post one loan-wise
		GL (against_voucher = Loan, merged across disbursements), while the breakdown table keeps
		each disbursement's contribution separately traceable via loan_disbursement."""
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)

		loan = create_loan(
			self.applicant,
			"Term Loan Product 5",
			60000,
			"Repay Over Number of Periods",
			4,
			applicant_type="Customer",
			repayment_start_date="2024-04-10",
			posting_date=posting_date,
			rate_of_interest=20,
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2025-12-05",
		)
		loan.submit()

		disbursement_1 = make_loan_disbursement_entry(
			loan.name, 36000, disbursement_date="2024-04-05", repayment_start_date="2024-04-10"
		)
		disbursement_2 = make_loan_disbursement_entry(
			loan.name, 24000, disbursement_date="2024-04-06", repayment_start_date="2024-04-11"
		)

		process_loan_interest_accrual_for_loans(posting_date="2024-04-20", loan=loan.name, company=COMPANY)

		accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 1},
			["name", "loan_disbursement", "process_loan_accounting_voucher"],
		)
		self.assertTrue(accruals, "expected daily accruals for the LOC loan")
		disbursements_seen = {a.loan_disbursement for a in accruals}
		self.assertEqual(
			disbursements_seen, {disbursement_1.name, disbursement_2.name},
			"expected accruals from both disbursements",
		)
		self.assertTrue(all(not a.process_loan_accounting_voucher for a in accruals), "all daily GL deferred")

		voucher = run_consolidation_for_loan(loan.name, get_last_day(posting_date), force=True)
		self.assertTrue(voucher)

		gl_rows = frappe.get_all(
			"GL Entry",
			{"voucher_no": voucher, "is_cancelled": 0},
			["against_voucher_type", "against_voucher"],
		)
		self.assertTrue(gl_rows)
		self.assertTrue(all(g.against_voucher_type == "Loan" for g in gl_rows))
		self.assertTrue(all(g.against_voucher == loan.name for g in gl_rows))

		details = frappe.get_all(
			"Process Loan Accounting Detail",
			{"parent": voucher},
			["loan_disbursement", "debit", "credit", "source_doc_count"],
		)
		self.assertTrue(details)
		detail_disbursements = {d.loan_disbursement for d in details}
		self.assertEqual(
			detail_disbursements, {disbursement_1.name, disbursement_2.name},
			"breakdown should trace both disbursements separately",
		)

		detail_debit = sum(flt(d.debit) for d in details)
		detail_credit = sum(flt(d.credit) for d in details)
		gl_totals = frappe.db.sql(
			"select sum(debit), sum(credit) from `tabGL Entry` where voucher_no=%s and is_cancelled=0",
			voucher,
		)[0]
		self.assertAlmostEqual(detail_debit, flt(gl_totals[0]), places=2)
		self.assertAlmostEqual(detail_credit, flt(gl_totals[1]), places=2)

		accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 1},
			["process_loan_accounting_voucher"],
		)
		self.assertTrue(all(a.process_loan_accounting_voucher == voucher for a in accruals))

	def test_loc_loan_demand_consolidates_correctly(self):
		"""Loan Demand (not just accrual) for LOC loans also defers and consolidates loan-wise."""
		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)

		loan = create_loan(
			self.applicant,
			"Term Loan Product 5",
			60000,
			"Repay Over Number of Periods",
			4,
			applicant_type="Customer",
			repayment_start_date="2024-04-10",
			posting_date=posting_date,
			rate_of_interest=20,
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2025-12-05",
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, 36000, disbursement_date="2024-04-05", repayment_start_date="2024-04-10"
		)

		process_daily_loan_demands(posting_date="2024-04-10", loan=loan.name)

		demands = frappe.get_all(
			"Loan Demand", {"loan": loan.name, "docstatus": 1}, ["name", "process_loan_accounting_voucher"]
		)
		self.assertTrue(demands, "expected loan demand for the LOC loan")
		self.assertTrue(all(not d.process_loan_accounting_voucher for d in demands), "demand GL deferred")

		voucher = run_consolidation_for_loan(loan.name, get_last_day(posting_date), force=True)
		self.assertTrue(voucher)

		demands = frappe.get_all(
			"Loan Demand", {"loan": loan.name, "docstatus": 1}, ["process_loan_accounting_voucher"]
		)
		self.assertTrue(all(d.process_loan_accounting_voucher == voucher for d in demands))

	def test_demand_deferral_gated_on_demand_date_not_posting_date(self):
		"""Deferral must gate on demand_date, not posting_date (always today), matching the date field
		the consolidation queries scope by -- otherwise a backdated demand can defer with no month
		that ever consolidates it."""
		demand_date = "2024-04-10"
		start_date = "2024-05-01"
		self.enable_consolidation(start_date)

		loan = create_loan(
			self.applicant,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=demand_date,
			posting_date=demand_date,
			rate_of_interest=23,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			1000000,
			disbursement_date=demand_date,
			repayment_start_date=demand_date,
		)

		process_daily_loan_demands(posting_date=demand_date, loan=loan.name)

		demands = frappe.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1},
			["name", "demand_date", "posting_date", "demand_subtype", "process_loan_accounting_voucher"],
		)
		self.assertTrue(demands, "expected a demand for the backdated period")
		for d in demands:
			self.assertLess(get_last_day(d.demand_date), getdate(start_date))
			self.assertGreaterEqual(getdate(d.posting_date), getdate(start_date))

		# with the fix, demand_date < start_date means consolidation is not enabled for this demand:
		# it must not be deferred into a consolidated voucher.
		self.assertTrue(
			all(not d.process_loan_accounting_voucher for d in demands),
			"a demand dated before start_date must not be linked to a consolidated voucher",
		)
		# Principal demands never carry their own GL (build_gl_map skips them); only check GL
		# posting for demand rows that would actually carry GL.
		gl_bearing = [d for d in demands if d.demand_subtype != "Principal"]
		self.assertTrue(
			all(self.gl_count(d.name) > 0 for d in gl_bearing),
			"a demand dated before start_date must post its own GL, not defer into a dead zone",
		)

		# consolidation for the (pre-start-date) demand month must find nothing to do -- the demand
		# already carries its own GL and was never deferred.
		voucher = run_consolidation_for_loan(loan.name, get_last_day(demand_date), force=True)
		self.assertFalse(voucher, "nothing should be deferred for a pre-start-date month")

	def test_colending_demand_gl_uses_full_amount_not_partner_split(self):
		"""Co-lending: Loan Demand GL must post the full demand_amount regardless of loan_partner /
		partner_share -- the partner split is a separate settlement concern, not a consolidation one."""
		loan_partner = "Test Loan Partner 1"
		if not frappe.db.exists("Loan Partner", loan_partner):
			create_loan_partner(
				loan_partner,
				loan_partner,
				partner_loan_share_percentage=80,
				effective_date="2024-01-01",
				repayment_schedule_type="EMI (PMT) based",
				partner_base_interest_rate=10,
				organization_type="Centralized",
				fldg_limit_calculation_component="Disbursement",
				type_of_fldg_applicable="Fixed Deposit Only",
				fldg_fixed_deposit_percentage=10,
			)

		posting_date = "2024-04-05"
		self.enable_consolidation(posting_date)

		repayment_start = add_months(posting_date, 1)
		loan = create_loan(
			self.applicant,
			"Personal Loan",
			280000,
			"Repay Over Number of Periods",
			loan_partner=loan_partner,
			repayment_periods=20,
			repayment_start_date=repayment_start,
			posting_date=posting_date,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, 280000, disbursement_date=posting_date, repayment_start_date=repayment_start
		)

		self.assertEqual(
			frappe.db.get_value("Loan", loan.name, "loan_partner"), loan_partner, "loan must be co-lent"
		)

		process_daily_loan_demands(posting_date=repayment_start, loan=loan.name)

		demands = frappe.get_all(
			"Loan Demand",
			{"loan": loan.name, "docstatus": 1, "demand_type": "EMI"},
			["name", "demand_subtype", "demand_amount", "partner_share", "loan_partner", "process_loan_accounting_voucher"],
		)
		self.assertTrue(demands, "expected EMI demand at the first repayment date")
		self.assertTrue(all(d.loan_partner == loan_partner for d in demands), "demand should inherit loan_partner")
		interest_demands = [d for d in demands if d.demand_subtype == "Interest"]
		self.assertTrue(interest_demands, "expected an interest demand to check partner_share against")
		for d in interest_demands:
			self.assertTrue(flt(d.partner_share) > 0, "partner_share should be computed for co-lent EMI")
			self.assertLess(
				flt(d.partner_share), flt(d.demand_amount), "partner_share is a split, not the full amount"
			)
		self.assertTrue(all(not d.process_loan_accounting_voucher for d in demands), "demand GL deferred")

		voucher = run_consolidation_for_loan(loan.name, get_last_day(repayment_start), force=True)
		self.assertTrue(voucher)

		# the consolidated GL for interest must equal the sum of full demand_amount, not partner_share
		details = frappe.get_all(
			"Process Loan Accounting Detail",
			{"parent": voucher, "source_type": "Loan Demand"},
			["debit", "credit", "source_document"],
		)
		self.assertTrue(details)
		posted_debit = sum(flt(d.debit) for d in details)
		full_amount_total = sum(flt(d.demand_amount) for d in interest_demands)
		partner_share_total = sum(flt(d.partner_share) for d in interest_demands)
		self.assertAlmostEqual(posted_debit, full_amount_total, places=2)
		self.assertNotAlmostEqual(posted_debit, partner_share_total, places=2)

		demands = frappe.get_all(
			"Loan Demand", {"loan": loan.name, "docstatus": 1, "demand_type": "EMI"}, ["process_loan_accounting_voucher"]
		)
		self.assertTrue(all(d.process_loan_accounting_voucher == voucher for d in demands))

	def test_npa_suspense_penalty_and_additional_interest_consolidated(self):
		"""NPA suspense consolidation must also cover penalty and additional-interest accruals, not
		just Normal Interest -- live_suspense_buckets has a separate branch for each."""
		from frappe.utils import get_first_day

		start = "2024-09-01"
		self.enable_consolidation(start)
		frappe.db.set_value(
			"Loan Product",
			"Term Loan Product 2",
			{
				"days_past_due_threshold_for_npa": 30,
				# fixture normally leaves these unset -- without them live_suspense_buckets'
				# penalty/additional-interest branches silently no-op (guarded, not a bug), so this
				# test would look like it passed without exercising them at all.
				"penalty_suspense_account": "Suspense Penalty Account - _TC",
				"additional_interest_suspense": "Suspense Income Account - _TC",
			},
		)

		loan = create_loan(
			self.applicant,
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

		# an unpaid EMI demand goes overdue -> daily penal interest + additional interest accrue
		process_loan_interest_accrual_for_loans(posting_date="2024-09-01", loan=loan.name)
		process_daily_loan_demands(posting_date="2024-09-16", loan=loan.name)
		for d in ["2024-09-30", "2024-10-31"]:
			process_loan_interest_accrual_for_loans(posting_date=d, loan=loan.name)

		create_process_loan_classification(
			posting_date="2024-10-05", loan=loan.name, force_update_dpd_in_loan=1
		)
		process_loan_interest_accrual_for_loans(posting_date="2024-11-30", loan=loan.name)

		npa_accruals = frappe.get_all(
			"Loan Interest Accrual",
			{
				"loan": loan.name,
				"docstatus": 1,
				"is_npa": 1,
				"unmark_npa": 0,
				"posting_date": ["between", ["2024-10-01", "2024-11-30"]],
			},
			["interest_type", "additional_interest_amount"],
		)
		self.assertTrue(npa_accruals, "expected NPA accruals over the consolidated months")
		interest_types = {a.interest_type for a in npa_accruals}
		self.assertTrue(
			len(interest_types) > 1 or any(flt(a.additional_interest_amount) for a in npa_accruals),
			"fixture must actually exercise more than plain Normal Interest to be a meaningful check "
			"(penalty interest_type or additional_interest_amount)",
		)

		for me in ["2024-10-31", "2024-11-30"]:
			run_consolidation_for_loan(loan.name, me, force=True)

		tags = frappe.get_all(
			"Journal Entry",
			{"loan": loan.name, "process_loan_accounting_month_end": ["is", "set"], "docstatus": 1},
			["name", "process_loan_accounting_month_end"],
		)
		self.assertTrue(tags, "consolidated suspense JEs should exist for NPA months")

		# Normal / Penal / Additional-interest suspense each use a distinct account pair, so one
		# NPA month legitimately produces multiple JEs sharing the same tag (one per account pair).
		# The real invariant is: no two JEs for the same month share the same account pair.
		by_month = {}
		for je in tags:
			by_month.setdefault(je.process_loan_accounting_month_end, []).append(je.name)

		for month_end, jes in by_month.items():
			seen_account_pairs = set()
			je_net_total = 0
			for je_name in jes:
				rows = frappe.get_all(
					"GL Entry", {"voucher_no": je_name, "is_cancelled": 0}, ["account", "debit", "credit"]
				)
				accounts = tuple(sorted(r.account for r in rows))
				self.assertNotIn(accounts, seen_account_pairs, "no duplicate suspense JE for the same account pair")
				seen_account_pairs.add(accounts)
				je_net_total += sum(
					flt(r.credit) - flt(r.debit) for r in rows if "uspense" in r.account
				)

			normal_live = frappe.db.sql(
				"""select sum(interest_amount) - sum(additional_interest_amount)
				from `tabLoan Interest Accrual`
				where loan=%s and docstatus=1 and is_npa=1 and unmark_npa=0 and interest_type='Normal Interest'
					and posting_date between %s and %s""",
				(loan.name, get_first_day(month_end), month_end),
			)[0][0] or 0
			penalty_live = frappe.db.sql(
				"""select sum(interest_amount) - sum(additional_interest_amount)
				from `tabLoan Interest Accrual`
				where loan=%s and docstatus=1 and is_npa=1 and unmark_npa=0 and interest_type!='Normal Interest'
					and posting_date between %s and %s""",
				(loan.name, get_first_day(month_end), month_end),
			)[0][0] or 0
			additional_live = frappe.db.sql(
				"""select sum(additional_interest_amount) from `tabLoan Interest Accrual`
				where loan=%s and docstatus=1 and is_npa=1 and unmark_npa=0
					and posting_date between %s and %s""",
				(loan.name, get_first_day(month_end), month_end),
			)[0][0] or 0
			live_total = flt(normal_live) + flt(penalty_live) + flt(additional_live)
			self.assertAlmostEqual(je_net_total, live_total, places=2)

		# ledger balances even with penalty + additional-interest suspense lines mixed in
		net = frappe.db.sql(
			"select sum(debit) - sum(credit) from `tabGL Entry` where against_voucher=%s and is_cancelled=0",
			loan.name,
		)[0][0] or 0
		self.assertAlmostEqual(net, 0, places=2)

	def test_repost_before_start_date_reconsolidates_only_post_cutoff_months(self):
		"""A repost whose repost_date is before loan_gl_consolidation_start_date must not choke or
		reconsolidate pre-cutoff months (which never had a voucher); it should clamp to the cutoff
		month and settle every month from there through the current open period."""
		start_date = "2024-05-01"
		self.enable_consolidation(start_date)

		posting_date = "2024-04-05"
		loan = self.make_loan_with_daily_accruals(posting_date, "2024-05-20")

		pre_cutoff_accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1, "posting_date": ["<", start_date]},
			["name", "process_loan_accounting_voucher"],
		)
		post_cutoff_accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1, "posting_date": [">=", start_date]},
			["name", "process_loan_accounting_voucher"],
		)
		self.assertTrue(pre_cutoff_accruals, "expected accruals before the cutoff")
		self.assertTrue(post_cutoff_accruals, "expected accruals on/after the cutoff")
		self.assertTrue(all(not a.process_loan_accounting_voucher for a in pre_cutoff_accruals))
		self.assertTrue(all(not a.process_loan_accounting_voucher for a in post_cutoff_accruals))
		for a in pre_cutoff_accruals:
			self.assertTrue(self.gl_count(a.name) > 0, "pre-cutoff accrual posts its own GL immediately")
		for a in post_cutoff_accruals:
			self.assertEqual(self.gl_count(a.name), 0, "post-cutoff accrual defers GL")

		# repost from a date before the cutoff -- must not touch pre-cutoff daily GL and must not
		# error out reconsolidating a month that was never deferred
		company = frappe.db.get_value("Loan", loan, "company")
		reconsolidate_gl_for_loan(loan, company, repost_date=posting_date, start_date=start_date)

		pre_cutoff_accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1, "posting_date": ["<", start_date]},
			["name", "process_loan_accounting_voucher"],
		)
		self.assertTrue(
			all(not a.process_loan_accounting_voucher for a in pre_cutoff_accruals),
			"pre-cutoff accruals must never be folded into a consolidated voucher",
		)
		for a in pre_cutoff_accruals:
			self.assertTrue(self.gl_count(a.name) > 0, "pre-cutoff GL must survive reconsolidation untouched")

		post_cutoff_accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1, "posting_date": [">=", start_date]},
			["name", "process_loan_accounting_voucher"],
		)
		self.assertTrue(
			all(a.process_loan_accounting_voucher for a in post_cutoff_accruals),
			"post-cutoff accruals must be consolidated by the reconsolidation loop",
		)

		# idempotent: re-running the reconsolidation loop must not double-post
		vouchers_before = frappe.get_all(
			"Process Loan Accounting", {"loan": loan, "docstatus": 1}, pluck="name"
		)
		income_before = self.consolidated_income(loan)
		reconsolidate_gl_for_loan(loan, company, repost_date=posting_date, start_date=start_date)
		vouchers_after = frappe.get_all(
			"Process Loan Accounting", {"loan": loan, "docstatus": 1}, pluck="name"
		)
		self.assertEqual(set(vouchers_before), set(vouchers_after), "no duplicate vouchers on re-run")
		self.assertEqual(self.consolidated_income(loan), income_before, "idempotent, no double posting")

	def test_mid_month_start_date_gives_partial_first_period(self):
		"""loan_gl_consolidation_start_date does not have to be the first of a month. The first
		voucher's period must start exactly at the start date (a partial first period), not at the
		calendar month's first day, and the following month's voucher must pick up right after it."""
		start_date = "2024-04-15"
		self.enable_consolidation(start_date)
		loan = self.make_loan_with_daily_accruals("2024-04-05", "2024-05-20")

		pre_start_accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan, "docstatus": 1, "posting_date": ["<", start_date]},
			pluck="name",
		)
		self.assertTrue(pre_start_accruals, "expected accruals before the mid-month start date")
		for a in pre_start_accruals:
			self.assertTrue(self.gl_count(a) > 0, "accrual before start date posts its own GL")

		april_voucher = run_consolidation_for_loan(loan, "2024-04-30", force=True)
		self.assertTrue(april_voucher, "expected a partial first period voucher for April")
		period_start, period_end = frappe.db.get_value(
			"Process Loan Accounting", april_voucher, ["period_start_date", "period_end_date"]
		)
		self.assertEqual(getdate(period_start), getdate(start_date), "first period starts at the start date")
		self.assertEqual(getdate(period_end), getdate("2024-04-30"))

		# accruals dated before the start date must not be swept into this partial period
		april_details = frappe.get_all(
			"Process Loan Accounting Detail", {"parent": april_voucher}, pluck="source_document"
		)
		self.assertFalse(
			set(pre_start_accruals) & set(d for d in april_details if d),
			"pre-start-date accruals must not appear in the first consolidated voucher",
		)

		may_voucher = run_consolidation_for_loan(loan, "2024-05-31", force=True)
		self.assertTrue(may_voucher, "expected May to consolidate too")
		may_period_start = frappe.db.get_value("Process Loan Accounting", may_voucher, "period_start_date")
		self.assertEqual(
			getdate(may_period_start),
			getdate("2024-05-01"),
			"second period picks up the day after the first period's end",
		)

	def test_completed_month_ends_lists_every_month_since_start(self):
		"""completed_month_ends must return every finished month from the start date through the
		most recently completed one -- the building block for missed-run catch-up."""
		months = completed_month_ends("2024-04-15", getdate("2024-07-10"))
		self.assertEqual(
			[getdate(m) for m in months],
			[getdate("2024-04-30"), getdate("2024-05-31"), getdate("2024-06-30")],
			"April through June are complete; July is still in progress and must not be included",
		)

		self.assertEqual(completed_month_ends("2024-04-15", getdate("2024-04-20")), [], "no month finished yet")

		# the scheduler runs ON a month's last day, not the day after -- that day must still count
		self.assertEqual(
			[getdate(m) for m in completed_month_ends("2024-04-15", getdate("2024-04-30"))],
			[getdate("2024-04-30")],
			"a month whose last day IS posting_date must be included, not deferred to the next tick",
		)

	def test_missed_scheduler_run_is_caught_up_on_next_tick(self):
		"""completed_month_ends (verified above) is what decides which months the scheduler catches
		up. This proves the other half: a month found that way still consolidates correctly on a
		later run, exactly as if the scheduler had reached it on time -- April's accruals must not
		be silently skipped just because nothing ran on April's own month-end."""
		start_date = "2024-04-01"
		self.enable_consolidation(start_date)
		loan = self.make_loan_with_daily_accruals(start_date, "2024-04-25")

		missed_months = completed_month_ends(start_date, getdate("2024-06-30"))
		self.assertIn(getdate("2024-04-30"), missed_months)

		for month_end in missed_months:
			run_consolidation_for_loan(loan, month_end, force=True)

		accruals = frappe.get_all(
			"Loan Interest Accrual", {"loan": loan, "docstatus": 1}, ["name", "process_loan_accounting_voucher"]
		)
		self.assertTrue(accruals, "expected April's daily accruals")
		self.assertTrue(
			all(a.process_loan_accounting_voucher for a in accruals),
			"April's accruals must be swept up even though nothing ran on April's own month-end",
		)
