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


def _consolidation_start_date(company, fallback):
	"""Docs dated before this were posted with their own daily GL and never got a voucher link --
	pending-consolidation queries must not pick them up just because consolidated_gl_voucher is null."""
	start_date = frappe.get_cached_value("Company", company, "loan_gl_consolidation_start_date")
	return getdate(start_date) if start_date else getdate(fallback)


class ProcessLoanAccounting(LoanController):
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

		# Posts on run date, not month_end_date, so it never writes into a closed period.
		if not self.posting_date:
			self.posting_date = getdate(nowdate())

		self.is_adjustment = cint(getdate(self.posting_date) != getdate(self.month_end_date))

	def on_submit(self):
		if not loan_accounting_enabled(self.company):
			return

		gl_map, covered = self.build_consolidated_gl()
		self.save_consolidation_details()

		if gl_map:
			self.make_gl_entries(gl_map, merge_entries=False)

		self.flag_covered_docs(covered)
		# Runs after flagging so the "live" NPA set reflects this run's cancellations/recreations.
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
		make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

		for je in frappe.get_all(
			"Journal Entry", {"user_remark": self.suspense_je_tag(), "docstatus": 1}, pluck="name"
		):
			doc = frappe.get_doc("Journal Entry", je)
			doc.flags.ignore_links = True
			doc.cancel()

		for doctype in CONSOLIDATED_SOURCES:
			frappe.db.set_value(
				doctype,
				{"consolidated_gl_voucher": self.name},
				{"consolidated_gl_voucher": None},
				update_modified=False,
			)

	def build_consolidated_gl(self):
		"""Aggregate deferred source GL into one consolidated map.

		Returns (gl_map, covered) where covered maps doctype -> source doc names to flag as posted.
		"""
		gl_buckets = {}
		detail_buckets = {}
		covered = {doctype: [] for doctype in CONSOLIDATED_SOURCES}

		for doctype in CONSOLIDATED_SOURCES:
			for name in self.get_deferred_docs(doctype):
				source = frappe.get_doc(doctype, name)
				sign = -1 if source.docstatus == 2 else 1
				for line in source.build_gl_map() or []:
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
		"""Source docs in this period not yet reflected in a consolidated voucher (or cancelled after one)."""
		date_field = "posting_date" if doctype == "Loan Interest Accrual" else "demand_date"

		src = frappe.qb.DocType(doctype)
		date_col = src[date_field]
		# Docs dated before the company's consolidation start date already posted their own daily
		# GL and never got a voucher link -- exclude them or they'd be wrongly folded in here too.
		period_start = max(getdate(self.period_start_date), self.consolidation_start_date())
		in_period = date_col[period_start : self.period_end_date]

		pending = (
			frappe.qb.from_(src)
			.select(src.name)
			.where(
				(src.loan == self.loan)
				& (src.docstatus == 1)
				& src.consolidated_gl_voucher.isnull()
				& in_period
			)
			.run(pluck=True)
		)

		reversed_after = (
			frappe.qb.from_(src)
			.select(src.name)
			.where(
				(src.loan == self.loan)
				& (src.docstatus == 2)
				& src.consolidated_gl_voucher.isnotnull()
				& in_period
			)
			.run(pluck=True)
		)

		return pending + reversed_after

	def consolidation_start_date(self):
		return _consolidation_start_date(self.company, self.period_start_date)

	def buckets_to_gl_map(self, buckets):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		gl_map = []

		for key, amounts in buckets.items():
			net = flt(amounts["debit"], precision) - flt(amounts["credit"], precision)
			if not net:
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
					# Blank when multiple docs merge into one line; trace those via # Docs / Ledger.
					"source_document": next(iter(source_docs)) if len(source_docs) == 1 else None,
					"loan_disbursement": loan_disbursement,
					"account": line.get("account"),
					"debit": net if net > 0 else 0,
					"credit": -net if net < 0 else 0,
					"source_doc_count": len(source_docs),
				},
			)

	def sync_consolidated_suspense_je(self):
		"""Recompute-from-live: cancel any existing consolidated NPA suspense JE for this loan+month,
		then post one fresh JE equal to the sum of live NPA accruals in the month."""
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
		return f"CONS-SUSPENSE::{self.loan}::{self.month_end_date}"

	def live_suspense_buckets(self):
		"""Suspense amounts (income -> suspense) from all live NPA accruals in the month."""
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
					frappe.db.set_value(
						doctype, name, "consolidated_gl_voucher", None, update_modified=False
					)
				else:
					frappe.db.set_value(
						doctype,
						name,
						{"consolidated_gl_voucher": self.name},
						update_modified=False,
					)


def run_consolidation_for_loan(loan, month_end_date=None, company=None, force=False):
	"""Create and submit one consolidated voucher for a single loan + month.

	Idempotent: re-running for the same loan+month posts only the delta. Returns the voucher name,
	or None if nothing to consolidate.
	"""
	company = company or frappe.db.get_value("Loan", loan, "company")
	if not company or not loan_accounting_enabled(company):
		return

	if not force and not gl_consolidation_enabled(company, month_end_date or nowdate()):
		return

	month_end_date = get_last_day(month_end_date or nowdate())
	period_start = get_first_day(month_end_date)

	if not loan_has_deferred_gl(loan, company, period_start, month_end_date):
		return

	doc = frappe.new_doc("Process Loan Accounting")
	doc.company = company
	doc.loan = loan
	doc.month_end_date = month_end_date
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def loan_has_deferred_gl(loan, company, period_start, period_end):
	"""Whether the loan has any deferred or reversal-pending accrual/demand in the period."""
	start_date = _consolidation_start_date(company, period_start)
	for doctype in CONSOLIDATED_SOURCES:
		date_field = "posting_date" if doctype == "Loan Interest Accrual" else "demand_date"
		src = frappe.qb.DocType(doctype)
		in_period = src[date_field][start_date:period_end]

		pending = (src.docstatus == 1) & src.consolidated_gl_voucher.isnull()
		reversal_pending = (src.docstatus == 2) & src.consolidated_gl_voucher.isnotnull()
		exists = (
			frappe.qb.from_(src)
			.select(src.name)
			.where((src.loan == loan) & in_period & (pending | reversal_pending))
			.limit(1)
			.run()
		)
		if exists:
			return True
	return False


def loans_with_deferred_gl(company, period_start, period_end):
	"""Loans of a company that have any deferred (or reversal-pending) accrual/demand in the period."""
	start_date = _consolidation_start_date(company, period_start)
	loans = set()
	for doctype in CONSOLIDATED_SOURCES:
		date_field = "posting_date" if doctype == "Loan Interest Accrual" else "demand_date"
		src = frappe.qb.DocType(doctype)
		in_period = src[date_field][start_date:period_end]

		pending = (src.docstatus == 1) & src.consolidated_gl_voucher.isnull()
		reversal_pending = (src.docstatus == 2) & src.consolidated_gl_voucher.isnotnull()
		loans.update(
			frappe.qb.from_(src)
			.select(src.loan)
			.distinct()
			.where((src.company == company) & in_period & (pending | reversal_pending))
			.run(pluck=True)
		)
	return [x for x in loans if x]


CONSOLIDATION_BATCH_SIZE = 3000


def run_consolidation_for_company(company, month_end_date=None, force=False):
	"""Enqueue consolidation of every loan of a company for the month, in batches (see process_loan_interest_accrual)."""
	if not loan_accounting_enabled(company):
		return

	if not force and not gl_consolidation_enabled(company, month_end_date or nowdate()):
		return

	month_end_date = get_last_day(month_end_date or nowdate())
	period_start = get_first_day(month_end_date)

	loans = loans_with_deferred_gl(company, period_start, month_end_date)
	for batch in get_batches(loans, CONSOLIDATION_BATCH_SIZE):
		frappe.enqueue(
			run_consolidation_for_loan_batch,
			loans=batch,
			month_end_date=month_end_date,
			company=company,
			queue="long",
			enqueue_after_commit=True,
		)


def get_batches(items, batch_size):
	for i in range(0, len(items), batch_size):
		yield items[i : i + batch_size]


def run_consolidation_for_loan_batch(loans, month_end_date, company):
	"""Consolidate a batch of loans for the month."""
	for loan in loans:
		try:
			run_consolidation_for_loan(loan, month_end_date, company=company, force=True)
		except Exception:
			frappe.log_error(
				title=f"Consolidated Loan GL failed for {loan}",
				reference_doctype="Loan",
				reference_name=loan,
			)
		# Commit per loan so one failure in the batch doesn't roll back earlier loans.
		frappe.db.commit()  # nosemgrep


def process_loan_accounting(month_end_date=None):
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
