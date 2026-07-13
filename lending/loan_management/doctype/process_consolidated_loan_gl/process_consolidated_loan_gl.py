# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, get_last_day, getdate, nowdate

from lending.loan_management.controllers.loan_controller import LoanController
from lending.loan_management.utils import gl_consolidation_enabled, loan_accounting_enabled

# Doctypes whose GL is deferred and folded into the consolidated voucher.
CONSOLIDATED_SOURCES = ("Loan Interest Accrual", "Loan Demand")

# GL dict keys that identify a distinct consolidated line. Amounts (debit/credit) are summed
# within a bucket; everything else must match for two source lines to merge.
BUCKET_KEYS = (
	"account",
	"against",
	"cost_center",
	"party_type",
	"party",
	"against_voucher_type",
	"against_voucher",
)


class ProcessConsolidatedLoanGL(LoanController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		company: DF.Link
		is_adjustment: DF.Check
		loan: DF.Link
		month_end_date: DF.Date
		period_end_date: DF.Date | None
		period_start_date: DF.Date | None
		posting_date: DF.Date
	# end: auto-generated types

	def validate(self):
		if not self.company:
			self.company = frappe.db.get_value("Loan", self.loan, "company")

		self.month_end_date = get_last_day(self.month_end_date)

		if not self.period_start_date:
			self.period_start_date = get_first_day(self.month_end_date)
		if not self.period_end_date:
			self.period_end_date = self.month_end_date

		# Consolidated GL always posts on the run date (today), matching the original per-doc demand
		# behaviour (Loan Demand set posting_date = today). When the daily scheduler runs on month-end,
		# "today" is month-end; a repost/backdated run posts in the current open period. This avoids
		# ever writing into a closed accounting period. The month it belongs to is identified by
		# month_end_date + the period fields, not by the GL date.
		if not self.posting_date:
			self.posting_date = getdate(nowdate())

		self.is_adjustment = cint(getdate(self.posting_date) != getdate(self.month_end_date))

	def on_submit(self):
		if not loan_accounting_enabled(self.company):
			return

		gl_map, covered = self.build_consolidated_gl()

		# build_consolidated_gl fills self.consolidation_details; persist it (doc is already submitted).
		self.save_consolidation_details()

		if gl_map:
			self.make_gl_entries(gl_map, merge_entries=False)

		self.flag_covered_docs(covered)

		# NPA suspense JE: recompute from live accruals AFTER flagging, so the "live" set reflects
		# this run's cancellations/recreations. One JE per month, always equal to live NPA income.
		self.sync_consolidated_suspense_je()

	def save_consolidation_details(self):
		for row in self.consolidation_details:
			row.parent = self.name
			row.parenttype = self.doctype
			row.parentfield = "consolidation_details"
			row.db_insert()

	def on_cancel(self):
		from erpnext.accounts.general_ledger import make_reverse_gl_entries

		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		# The consolidated GL rows are read back from the ledger and reversed (immutable-ledger safe:
		# reversal is a fresh forward-dated entry, not an in-place edit).
		make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

		# Cancel this loan+month's consolidated NPA suspense JE(s) (tagged by loan+month).
		for je in frappe.get_all(
			"Journal Entry", {"user_remark": self.suspense_je_tag(), "docstatus": 1}, pluck="name"
		):
			doc = frappe.get_doc("Journal Entry", je)
			doc.flags.ignore_links = True
			doc.cancel()

		# Re-open the covered source docs so a subsequent run reconsolidates them.
		for doctype in CONSOLIDATED_SOURCES:
			frappe.db.set_value(
				doctype,
				{"consolidated_gl_voucher": self.name},
				{"gl_posted": 0, "consolidated_gl_voucher": None},
				update_modified=False,
			)

	def build_consolidated_gl(self):
		"""Aggregate deferred source GL into one consolidated map.

		Returns (gl_map, covered) where covered maps doctype -> list of source doc names to flag
		as posted once the voucher is submitted. Also fills the consolidation_details child table so
		the voucher shows what it rolled up (account, source type, amount, source doc count).
		"""
		# GL buckets are loan-wise (against_voucher = Loan). Detail buckets add loan_disbursement so
		# LOC loans (accrual/demand tracked per disbursement) are traceable in the breakdown table.
		gl_buckets = {}
		detail_buckets = {}
		covered = {doctype: [] for doctype in CONSOLIDATED_SOURCES}

		for doctype in CONSOLIDATED_SOURCES:
			for name in self.get_deferred_docs(doctype):
				source = frappe.get_doc(doctype, name)
				sign = -1 if source.docstatus == 2 else 1
				for line in source.build_gl_map():
					key = tuple(line.get(k) for k in BUCKET_KEYS)
					gl = gl_buckets.setdefault(key, {"debit": 0.0, "credit": 0.0})
					gl["debit"] += sign * flt(line.get("debit"))
					gl["credit"] += sign * flt(line.get("credit"))

					detail_key = (doctype, source.get("loan_disbursement")) + key
					detail = detail_buckets.setdefault(
						detail_key, {"debit": 0.0, "credit": 0.0, "source_docs": set()}
					)
					detail["debit"] += sign * flt(line.get("debit"))
					detail["credit"] += sign * flt(line.get("credit"))
					detail["source_docs"].add(source.name)

				covered[doctype].append(name)

		gl_map = self.buckets_to_gl_map(gl_buckets)
		self.fill_consolidation_details(detail_buckets)
		return gl_map, covered

	def get_deferred_docs(self, doctype):
		"""Source docs in this period whose GL is not yet reflected in a consolidated voucher.

		- docstatus 1 with gl_posted 0: newly accrued/demanded, not yet consolidated.
		- docstatus 2 with a consolidated voucher: cancelled after consolidation, needs reversing delta.
		"""
		date_field = "posting_date" if doctype == "Loan Interest Accrual" else "demand_date"

		src = frappe.qb.DocType(doctype)
		date_col = src[date_field]
		in_period = date_col[self.period_start_date : self.period_end_date]

		# gl_posted=0 AND no live consolidated voucher: guards against re-posting a doc whose GL is
		# already in the ledger (double-count protection if a doc is ever left half-reset).
		pending = (
			frappe.qb.from_(src)
			.select(src.name)
			.where(
				(src.loan == self.loan)
				& (src.docstatus == 1)
				& (src.gl_posted == 0)
				& src.consolidated_gl_voucher.isnull()
				& in_period
			)
			.run(pluck=True)
		)

		# cancelled after consolidation -> needs a reversing delta
		reversed_after = (
			frappe.qb.from_(src)
			.select(src.name)
			.where(
				(src.loan == self.loan)
				& (src.docstatus == 2)
				& (src.gl_posted == 1)
				& src.consolidated_gl_voucher.isnotnull()
				& in_period
			)
			.run(pluck=True)
		)

		return pending + reversed_after

	def buckets_to_gl_map(self, buckets):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		gl_map = []

		for key, amounts in buckets.items():
			net = flt(amounts["debit"], precision) - flt(amounts["credit"], precision)
			if not net:
				# Fully offset within the period (e.g. accrued then reversed) -> no GL row.
				continue

			args = dict(zip(BUCKET_KEYS, key, strict=True))
			args["posting_date"] = self.posting_date
			if net > 0:
				args["debit"] = net
				args["debit_in_account_currency"] = net
			else:
				args["credit"] = -net
				args["credit_in_account_currency"] = -net

			args["remarks"] = _("Consolidated loan GL for {0} ({1} to {2})").format(
				self.loan, self.period_start_date, self.period_end_date
			)
			gl_map.append(self.get_gl_dict(args))

		return gl_map

	def fill_consolidation_details(self, detail_buckets):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		self.consolidation_details = []

		for key, amounts in detail_buckets.items():
			net = flt(amounts["debit"], precision) - flt(amounts["credit"], precision)
			if not net:
				continue

			source_type, loan_disbursement = key[0], key[1]
			line = dict(zip(BUCKET_KEYS, key[2:], strict=True))
			source_docs = amounts["source_docs"]
			self.append(
				"consolidation_details",
				{
					"source_type": source_type,
					# Link the actual source doc only when a single one feeds this line; a merged
					# line (many docs) leaves it blank -- trace those via # Docs / View Ledger.
					"source_document": next(iter(source_docs)) if len(source_docs) == 1 else None,
					"loan_disbursement": loan_disbursement,
					"account": line.get("account"),
					"debit": net if net > 0 else 0,
					"credit": -net if net < 0 else 0,
					"source_doc_count": len(source_docs),
				},
			)

	def sync_consolidated_suspense_je(self):
		"""Make the month's consolidated NPA suspense JE equal the sum of its LIVE NPA accruals.

		Recompute-from-live (not delta): cancel any existing consolidated suspense JE for this
		loan+month, then post one fresh JE for the current total. This is self-correcting -- after any
		cancel/repost, the JE always matches reality, so debugging is a single check: does the live
		suspense JE for a month equal the sum of live NPA accruals in that month?
		"""
		# Cancel any suspense JE already posted for this loan+month (tagged with the month-end date).
		tag = self.suspense_je_tag()
		for je in frappe.get_all("Journal Entry", {"user_remark": tag, "docstatus": 1}, pluck="name"):
			doc = frappe.get_doc("Journal Entry", je)
			doc.flags.ignore_links = True
			doc.cancel()

		buckets = self.live_suspense_buckets()
		if not buckets:
			return

		import erpnext

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		cost_center = erpnext.get_default_cost_center(self.company)
		remark = _("Consolidated NPA suspense for {0} ({1} to {2})").format(
			self.loan, self.period_start_date, self.period_end_date
		)

		for (debit_account, credit_account), amount in buckets.items():
			amount = flt(amount, precision)
			if not amount:
				continue
			je = frappe.get_doc(
				{
					"doctype": "Journal Entry",
					"voucher_type": "Journal Entry",
					"posting_date": self.posting_date,
					"company": self.company,
					"accounts": [
						{
							"account": debit_account,
							"debit_in_account_currency": amount,
							"debit": amount,
							"reference_type": "Loan",
							"reference_name": self.loan,
							"cost_center": cost_center,
						},
						{
							"account": credit_account,
							"credit_in_account_currency": amount,
							"credit": amount,
							"reference_type": "Loan",
							"reference_name": self.loan,
							"cost_center": cost_center,
						},
					],
					"remarks": remark,
					"user_remark": tag,
				}
			)
			je.flags.ignore_permissions = True
			je.submit()

	def suspense_je_tag(self):
		"""Stable tag linking suspense JEs to this loan+month (survives voucher delta re-runs)."""
		return f"CONS-SUSPENSE::{self.loan}::{self.month_end_date}"

	def live_suspense_buckets(self):
		"""Target suspense amounts (income -> suspense) from all LIVE NPA accruals in the month."""
		if frappe.db.get_value("Loan", self.loan, "status") == "Written Off":
			return {}

		accruals = frappe.get_all(
			"Loan Interest Accrual",
			filters={
				"loan": self.loan,
				"docstatus": 1,
				"is_npa": 1,
				"unmark_npa": 0,
				"posting_date": ["between", [self.period_start_date, self.period_end_date]],
			},
			fields=["loan_product", "interest_type", "interest_amount", "additional_interest_amount"],
		)

		buckets = {}
		for a in accruals:
			accounts = frappe.get_cached_value(
				"Loan Product",
				a.loan_product,
				(
					"suspense_interest_income",
					"interest_income_account",
					"penalty_suspense_account",
					"penalty_income_account",
					"additional_interest_income",
					"additional_interest_suspense",
				),
				as_dict=1,
			)
			if not accounts:
				continue

			if a.interest_type == "Normal Interest":
				debit_account, credit_account = accounts.interest_income_account, accounts.suspense_interest_income
			else:
				debit_account, credit_account = accounts.penalty_income_account, accounts.penalty_suspense_account

			normal_amount = flt(a.interest_amount) - flt(a.additional_interest_amount)
			if normal_amount and debit_account and credit_account:
				key = (debit_account, credit_account)
				buckets[key] = buckets.get(key, 0.0) + normal_amount

			if flt(a.additional_interest_amount):
				key = (accounts.additional_interest_income, accounts.additional_interest_suspense)
				if all(key):
					buckets[key] = buckets.get(key, 0.0) + flt(a.additional_interest_amount)

		return buckets

	def flag_covered_docs(self, covered):
		for doctype, names in covered.items():
			for name in names:
				docstatus = frappe.db.get_value(doctype, name, "docstatus")
				if docstatus == 2:
					# Reversal absorbed: clear the link so it is not reversed again.
					frappe.db.set_value(
						doctype, name, "consolidated_gl_voucher", None, update_modified=False
					)
				else:
					frappe.db.set_value(
						doctype,
						name,
						{"gl_posted": 1, "consolidated_gl_voucher": self.name},
						update_modified=False,
					)


def run_consolidation_for_loan(loan, month_end_date=None, company=None, force=False):
	"""Create and submit one consolidated voucher for a single loan + month.

	Idempotent: re-running for the same loan+month posts only the delta of newly deferred / newly
	reversed source docs, so mid-month cancellations, backdated repayments and repeated reposts all
	settle without rewriting history. Returns the voucher name, or None if nothing to consolidate.
	"""
	company = company or frappe.db.get_value("Loan", loan, "company")
	if not company or not loan_accounting_enabled(company):
		return

	if not force and not gl_consolidation_enabled(company, month_end_date or nowdate()):
		return

	month_end_date = get_last_day(month_end_date or nowdate())
	period_start = get_first_day(month_end_date)

	# Skip months with nothing to consolidate so we never create empty vouchers (e.g. a repost that
	# loops from its date up to today across months that have no accrual/demand yet).
	if not loan_has_deferred_gl(loan, period_start, month_end_date):
		return

	doc = frappe.new_doc("Process Consolidated Loan GL")
	doc.company = company
	doc.loan = loan
	doc.month_end_date = month_end_date
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def loan_has_deferred_gl(loan, period_start, period_end):
	"""Whether the loan has any deferred or reversal-pending accrual/demand in the period."""
	for doctype in CONSOLIDATED_SOURCES:
		date_field = "posting_date" if doctype == "Loan Interest Accrual" else "demand_date"
		src = frappe.qb.DocType(doctype)
		in_period = src[date_field][period_start:period_end]

		deferred = (src.docstatus == 1) & (src.gl_posted == 0)
		reversal_pending = (
			(src.docstatus == 2)
			& (src.gl_posted == 1)
			& src.consolidated_gl_voucher.isnotnull()
		)
		exists = (
			frappe.qb.from_(src)
			.select(src.name)
			.where((src.loan == loan) & in_period & (deferred | reversal_pending))
			.limit(1)
			.run()
		)
		if exists:
			return True
	return False


def loans_with_deferred_gl(company, period_start, period_end):
	"""Loans of a company that have any deferred (or reversal-pending) accrual/demand in the period."""
	loans = set()
	for doctype in CONSOLIDATED_SOURCES:
		date_field = "posting_date" if doctype == "Loan Interest Accrual" else "demand_date"
		src = frappe.qb.DocType(doctype)
		in_period = src[date_field][period_start:period_end]

		# deferred (not yet consolidated) or cancelled-after-consolidation (needs reversing delta)
		deferred = (src.docstatus == 1) & (src.gl_posted == 0)
		reversal_pending = (
			(src.docstatus == 2)
			& (src.gl_posted == 1)
			& src.consolidated_gl_voucher.isnotnull()
		)
		loans.update(
			frappe.qb.from_(src)
			.select(src.loan)
			.distinct()
			.where((src.company == company) & in_period & (deferred | reversal_pending))
			.run(pluck=True)
		)
	return [x for x in loans if x]


def run_consolidation_for_company(company, month_end_date=None, force=False):
	"""Consolidate every loan of a company for the month: one voucher per loan. Returns voucher names."""
	if not loan_accounting_enabled(company):
		return []

	if not force and not gl_consolidation_enabled(company, month_end_date or nowdate()):
		return []

	month_end_date = get_last_day(month_end_date or nowdate())
	period_start = get_first_day(month_end_date)

	vouchers = []
	for loan in loans_with_deferred_gl(company, period_start, month_end_date):
		v = run_consolidation_for_loan(loan, month_end_date, company=company, force=True)
		if v:
			vouchers.append(v)
	return vouchers


def process_consolidated_loan_gl(month_end_date=None):
	"""Scheduler entry point. Runs on the last day of the month for every enabled company."""
	posting_date = getdate(month_end_date or nowdate())

	# Only act on an actual month-end unless a date is passed explicitly.
	if not month_end_date and posting_date != getdate(get_last_day(posting_date)):
		return

	company = frappe.qb.DocType("Company")
	companies = (
		frappe.qb.from_(company)
		.select(company.name)
		.where((company.loan_gl_consolidation == 1) & (company.enable_loan_accounting == 1))
		.run(pluck=True)
	)

	for company in companies:
		if not gl_consolidation_enabled(company, posting_date):
			continue
		frappe.enqueue(
			run_consolidation_for_company,
			queue="long",
			company=company,
			month_end_date=posting_date,
			job_id=f"consolidate-loan-gl::{company}::{posting_date}",
			deduplicate=True,
		)
