# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt, get_last_day

from lending.loan_management.doctype.process_consolidated_loan_gl.process_consolidated_loan_gl import (
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
	create_loan_write_off,
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
			["source_type", "source_document", "account", "debit", "credit", "source_doc_count"],
		)
		self.assertTrue(details, "consolidation_details should be populated")
		self.assertTrue(all(d.source_doc_count > 0 for d in details))

		# a single-doc line links its source document; a merged line does not
		for d in details:
			if d.source_doc_count == 1:
				self.assertTrue(d.source_document, "single-doc line should link its source")
				self.assertTrue(
					frappe.db.exists(d.source_type, d.source_document),
					"linked source document must exist and match its type",
				)
			else:
				self.assertFalse(d.source_document, "merged line must not link one document")

		# the breakdown reconciles to the posted GL exactly
		detail_debit = sum(flt(d.debit) for d in details)
		detail_credit = sum(flt(d.credit) for d in details)
		gl_totals = frappe.db.sql(
			"select sum(debit), sum(credit) from `tabGL Entry` where voucher_no=%s and is_cancelled=0",
			voucher,
		)[0]
		self.assertAlmostEqual(detail_debit, flt(gl_totals[0]), places=2)
		self.assertAlmostEqual(detail_credit, flt(gl_totals[1]), places=2)
		self.assertAlmostEqual(detail_debit, detail_credit, places=2)

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

		# NPA accruals defer their suspense JE (no per-accrual JE link)
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

		# one consolidated suspense JE per NPA month, each equal to that month's live NPA interest
		tags = frappe.get_all(
			"Journal Entry",
			{"user_remark": ["like", f"CONS-SUSPENSE::{loan.name}::%"], "docstatus": 1},
			["name", "user_remark"],
		)
		self.assertTrue(tags, "consolidated suspense JEs should exist for NPA months")
		seen = set()
		for je in tags:
			self.assertNotIn(je.user_remark, seen, "no duplicate suspense JE per month")
			seen.add(je.user_remark)
			month_end = je.user_remark.split("::")[-1]
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

		# ledger balances
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
				"Journal Entry", {"user_remark": ["like", f"CONS-SUSPENSE::{loan}::%"], "docstatus": 1}
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

		# the voucher (if any) only carries GL for pre-write-off accruals
		if voucher:
			detail_docs = frappe.get_all(
				"Consolidated Loan GL Detail", {"parent": voucher, "source_type": "Loan Interest Accrual"},
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
			{"loan": loan, "docstatus": 1, "gl_posted": 1, "interest_amount": [">", 0]},
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

		frappe.get_doc("Process Consolidated Loan GL", voucher).cancel()

		# original rows are untouched under immutable ledger -- not marked cancelled
		for row in original_rows:
			gl = frappe.db.get_value("GL Entry", row.name, ["is_cancelled", "debit", "credit"], as_dict=True)
			self.assertEqual(gl.is_cancelled, 0)
			self.assertAlmostEqual(flt(gl.debit), flt(row.debit), places=2)
			self.assertAlmostEqual(flt(gl.credit), flt(row.credit), places=2)

		# new forward-dated reversing rows were added alongside the originals, not replacing them
		live_rows = frappe.get_all("GL Entry", {"voucher_no": voucher, "is_cancelled": 0})
		self.assertEqual(len(live_rows), original_row_count * 2)

		# original + reversal net to zero against the loan
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

		# after repost + reconsolidation, each NPA month's suspense JE still equals live NPA interest
		tags = frappe.get_all(
			"Journal Entry",
			{"user_remark": ["like", f"CONS-SUSPENSE::{loan.name}::%"], "docstatus": 1},
			["name", "user_remark"],
		)
		self.assertTrue(tags, "consolidated suspense JEs should exist after repost")
		seen = set()
		for je in tags:
			self.assertNotIn(je.user_remark, seen, "no duplicate suspense JE per month after repost")
			seen.add(je.user_remark)
			month_end = je.user_remark.split("::")[-1]
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

		# overall ledger still balances after repost + reconsolidation
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
			["name", "loan_disbursement", "gl_posted"],
		)
		self.assertTrue(accruals, "expected daily accruals for the LOC loan")
		disbursements_seen = {a.loan_disbursement for a in accruals}
		self.assertEqual(
			disbursements_seen, {disbursement_1.name, disbursement_2.name},
			"expected accruals from both disbursements",
		)
		self.assertTrue(all(a.gl_posted == 0 for a in accruals), "all daily GL deferred")

		voucher = run_consolidation_for_loan(loan.name, get_last_day(posting_date), force=True)
		self.assertTrue(voucher)

		# GL is loan-wise: one against_voucher = Loan, not split per disbursement
		gl_rows = frappe.get_all(
			"GL Entry",
			{"voucher_no": voucher, "is_cancelled": 0},
			["against_voucher_type", "against_voucher"],
		)
		self.assertTrue(gl_rows)
		self.assertTrue(all(g.against_voucher_type == "Loan" for g in gl_rows))
		self.assertTrue(all(g.against_voucher == loan.name for g in gl_rows))

		# the breakdown table keeps each disbursement's contribution separately traceable
		details = frappe.get_all(
			"Consolidated Loan GL Detail",
			{"parent": voucher},
			["loan_disbursement", "debit", "credit", "source_doc_count"],
		)
		self.assertTrue(details)
		detail_disbursements = {d.loan_disbursement for d in details}
		self.assertEqual(
			detail_disbursements, {disbursement_1.name, disbursement_2.name},
			"breakdown should trace both disbursements separately",
		)

		# breakdown reconciles to the posted GL exactly, even though it's split by disbursement
		detail_debit = sum(flt(d.debit) for d in details)
		detail_credit = sum(flt(d.credit) for d in details)
		gl_totals = frappe.db.sql(
			"select sum(debit), sum(credit) from `tabGL Entry` where voucher_no=%s and is_cancelled=0",
			voucher,
		)[0]
		self.assertAlmostEqual(detail_debit, flt(gl_totals[0]), places=2)
		self.assertAlmostEqual(detail_credit, flt(gl_totals[1]), places=2)

		# all accruals from both disbursements are flagged posted and linked to the one voucher
		accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 1},
			["gl_posted", "consolidated_gl_voucher"],
		)
		self.assertTrue(all(a.gl_posted == 1 for a in accruals))
		self.assertTrue(all(a.consolidated_gl_voucher == voucher for a in accruals))

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
			"Loan Demand", {"loan": loan.name, "docstatus": 1}, ["name", "gl_posted"]
		)
		self.assertTrue(demands, "expected loan demand for the LOC loan")
		self.assertTrue(all(d.gl_posted == 0 for d in demands), "demand GL deferred")

		voucher = run_consolidation_for_loan(loan.name, get_last_day(posting_date), force=True)
		self.assertTrue(voucher)

		demands = frappe.get_all(
			"Loan Demand", {"loan": loan.name, "docstatus": 1}, ["gl_posted", "consolidated_gl_voucher"]
		)
		self.assertTrue(all(d.gl_posted == 1 for d in demands))
		self.assertTrue(all(d.consolidated_gl_voucher == voucher for d in demands))
