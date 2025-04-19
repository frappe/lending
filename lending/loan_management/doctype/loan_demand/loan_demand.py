# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_repayment.loan_repayment import update_installment_counts


class LoanDemand(AccountsController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		applicant: DF.DynamicLink | None
		applicant_type: DF.Link | None
		company: DF.Link | None
		cost_center: DF.Link | None
		demand_amount: DF.Currency
		demand_date: DF.Datetime | None
		demand_subtype: DF.Data | None
		demand_type: DF.Literal["EMI", "Penalty", "Normal", "Charges", "BPI", "Additional Interest"]
		disbursement_date: DF.Date | None
		invoice_date: DF.Date | None
		is_term_loan: DF.Check
		loan: DF.Link | None
		loan_disbursement: DF.Link | None
		loan_partner: DF.Link | None
		loan_product: DF.Link | None
		loan_repayment: DF.Link | None
		loan_repayment_schedule: DF.Link | None
		outstanding_amount: DF.Currency
		paid_amount: DF.Currency
		partner_share: DF.Currency
		partner_share_allocated: DF.Currency
		posting_date: DF.Datetime | None
		process_loan_demand: DF.Link | None
		repayment_schedule_detail: DF.Data | None
		sales_invoice: DF.Link | None
		waived_amount: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.outstanding_amount = flt(self.demand_amount) - flt(self.paid_amount)
		self.partner_share_allocated = 0

		if self.get("loan_partner"):
			if self.demand_type == "EMI" and self.demand_subtype == "Principal":
				partner_share_field = "principal_amount"
			elif self.demand_type == "EMI" and self.demand_subtype == "Interest":
				partner_share_field = "interest_amount"

			if self.demand_type == "EMI":
				self.partner_share = frappe.db.get_value(
					"Co-Lender Schedule",
					{"parent": self.loan_repayment_schedule, "payment_date": self.demand_date},
					partner_share_field,
				)

	def on_submit(self):
		from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
			process_loan_interest_accrual_for_loans,
		)

		if self.demand_subtype in ("Principal", "Interest", "Penalty", "Additional Interest"):
			self.make_gl_entries()

		self.update_repayment_schedule()

		if (
			not frappe.flags.on_repost
			and self.demand_type in ("EMI", "Normal")
			and self.demand_subtype == "Interest"
		):
			process_loan_interest_accrual_for_loans(
				posting_date=add_days(self.demand_date, -1),
				loan=self.loan,
				company=self.company,
				from_demand=True,
			)

	def update_repayment_schedule(self, cancel=0):
		if self.repayment_schedule_detail:
			frappe.db.set_value(
				"Repayment Schedule", self.repayment_schedule_detail, "demand_generated", cint(not cancel)
			)

	def on_cancel(self):
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries(cancel=1)
		self.update_repayment_schedule(cancel=1)
		self.make_credit_note()

	def make_credit_note(self):
		if not self.demand_type == "Charges":
			return

		if frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus") == 1:
			make_credit_note(
				self.company,
				self.demand_subtype,
				self.applicant,
				self.loan,
				self.sales_invoice,
				self.demand_date,
			)

	def make_gl_entries(self, cancel=0):
		gl_entries = []

		if self.demand_subtype == "Principal":
			return

		if self.demand_type == "Charges":
			return

		loan_status = frappe.db.get_value("Loan", self.loan, "status", cache=True)
		if loan_status == "Written Off":
			return

		party_type = ""
		party = ""

		if self.demand_type == "BPI":
			fields = ["interest_receivable_account", "broken_period_interest_recovery_account"]
			party_type = self.applicant_type
			party = self.applicant
		elif self.demand_subtype == "Interest":
			fields = ["interest_accrued_account", "interest_receivable_account"]
		elif self.demand_subtype == "Penalty":
			fields = ["penalty_accrued_account", "penalty_receivable_account"]
		elif self.demand_subtype == "Additional Interest":
			fields = ["additional_interest_accrued", "additional_interest_receivable"]

		accrual_account, receivable_account = frappe.db.get_value(
			"Loan Product", self.loan_product, fields
		)

		if not accrual_account:
			frappe.throw(
				_("Please set {0} Accrual Account in Loan Product {1}").format(
					self.demand_subtype, self.loan_product
				)
			)

		if not receivable_account:
			frappe.throw(
				_("Please set {0} Receivable Account in Loan Product {1}").format(
					self.demand_subtype, self.loan_product
				)
			)

		gl_entries = self.add_gl_entries(
			gl_entries, receivable_account, accrual_account, party_type, party
		)

		if self.demand_type == "BPI":
			receivable_account, accrual_account = frappe.db.get_value(
				"Loan Product", self.loan_product, ["interest_receivable_account", "interest_accrued_account"]
			)

			gl_entries = self.add_gl_entries(
				gl_entries, receivable_account, accrual_account, party_type, party
			)

		make_gl_entries(gl_entries, cancel=cancel, merge_entries=False, adv_adj=0)

	def add_gl_entries(
		self, gl_entries, receivable_account, accrual_account, party_type=None, party=None
	):
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		if flt(self.demand_amount, precision):
			gl_entries.append(
				self.get_gl_dict(
					{
						"posting_date": self.posting_date or self.demand_date,
						"account": receivable_account,
						"against": accrual_account,
						"debit": self.demand_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.loan,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"cost_center": self.cost_center,
					}
				)
			)

			gl_entries.append(
				self.get_gl_dict(
					{
						"posting_date": self.posting_date or self.demand_date,
						"account": accrual_account,
						"against": receivable_account,
						"credit": self.demand_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.loan,
						"cost_center": self.cost_center,
						"party_type": party_type,
						"party": party,
					}
				)
			)

		return gl_entries


def make_loan_demand_for_term_loans(
	posting_date,
	loan_product=None,
	loan=None,
	process_loan_demand=None,
	loan_disbursement=None,
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	open_loans = get_open_loans(is_term_loan=1, loan_product=loan_product, loan=loan)

	if loan:
		process_term_loan_batch(
			open_loans, posting_date, process_loan_demand, loan_disbursement, precision
		)
	else:
		BATCH_SIZE = 5000
		batch_list = list(get_batches(open_loans, BATCH_SIZE))

		for batch in batch_list:
			frappe.enqueue(
				process_term_loan_batch,
				loans=batch,
				posting_date=posting_date,
				process_loan_demand=process_loan_demand,
				loan_disbursement=loan_disbursement,
				precision=precision,
				queue="long",
				enqueue_after_commit=True,
			)


def process_term_loan_batch(
	loans, posting_date, process_loan_demand, loan_disbursement, precision
):
	freeze_dates = get_freeze_date_map(loans)

	schedule_filters = {
		"loan": ["in", loans],
		"status": "Active",
		"docstatus": 1,
	}

	if loan_disbursement:
		schedule_filters["loan_disbursement"] = loan_disbursement

	loan_repayment_schedules = frappe.db.get_all(
		"Loan Repayment Schedule",
		filters=schedule_filters,
		fields=["name", "loan", "loan_disbursement", "repayment_start_date"],
	)

	loan_repayment_schedule_map = frappe._dict()
	disbursement_map = frappe._dict()
	start_date_map = frappe._dict()

	for schedule in loan_repayment_schedules:
		loan_repayment_schedule_map[schedule.name] = schedule.loan
		disbursement_map[schedule.name] = schedule.loan_disbursement
		start_date_map[schedule.name] = schedule.repayment_start_date

	repayment_schedules = loan_repayment_schedule_map.keys()

	emi_rows = frappe.db.get_all(
		"Repayment Schedule",
		filters={
			"parent": ("in", repayment_schedules),
			"payment_date": ("<=", posting_date),
			"demand_generated": 0,
		},
		fields=["name", "parent", "principal_amount", "interest_amount", "payment_date"],
		order_by="payment_date asc",
	)

	for row in emi_rows:
		try:
			freeze_date = freeze_dates.get(loan_repayment_schedule_map.get(row.parent))
			if freeze_date and getdate(freeze_date) <= getdate(row.payment_date):
				continue

			paid_amount = 0

			if not row.principal_amount and getdate(row.payment_date) < getdate(
				start_date_map.get(row.parent)
			):
				demand_type = "BPI"
				paid_amount = row.interest_amount
			else:
				demand_type = "EMI"

			if row.interest_amount:
				create_loan_demand(
					loan_repayment_schedule_map.get(row.parent),
					row.payment_date,
					demand_type,
					"Interest",
					flt(row.interest_amount, precision),
					loan_repayment_schedule=row.parent,
					loan_disbursement=disbursement_map.get(row.parent),
					repayment_schedule_detail=row.name,
					process_loan_demand=process_loan_demand,
					paid_amount=paid_amount,
					posting_date=posting_date,
				)

			if row.principal_amount:
				create_loan_demand(
					loan_repayment_schedule_map.get(row.parent),
					row.payment_date,
					demand_type,
					"Principal",
					flt(row.principal_amount, precision),
					loan_repayment_schedule=row.parent,
					loan_disbursement=disbursement_map.get(row.parent),
					repayment_schedule_detail=row.name,
					process_loan_demand=process_loan_demand,
					paid_amount=paid_amount,
					posting_date=posting_date,
				)

			update_installment_counts(loan_repayment_schedule_map.get(row.parent))

			if len(loans) > 1:
				frappe.db.commit()
		except Exception as e:
			if len(loans) > 1:
				frappe.log_error(
					title="Term Loan Demand Generation Error",
					message=frappe.get_traceback(),
					reference_doctype="Loan",
					reference_name=loan_repayment_schedule_map.get(row.parent),
				)
			else:
				raise e

			if len(loans) > 1:
				frappe.db.rollback()


def make_loan_demand_for_demand_loans(
	posting_date,
	loan_product=None,
	loan=None,
	process_loan_demand=None,
):
	open_loans = get_open_loans(is_term_loan=0, loan_product=loan_product, loan=loan)

	if loan:
		process_demand_loan_batch(open_loans, posting_date, process_loan_demand)
	else:
		BATCH_SIZE = 5000
		batch_list = list(get_batches(open_loans, BATCH_SIZE))

		for batch in batch_list:
			frappe.enqueue(
				process_demand_loan_batch,
				loans=batch,
				posting_date=posting_date,
				process_loan_demand=process_loan_demand,
				queue="long",
				enqueue_after_commit=True,
			)


def process_demand_loan_batch(loans, posting_date, process_loan_demand):
	for loan in loans:
		try:
			make_loan_demand_for_demand_loan(posting_date, loan, process_loan_demand)
		except Exception as e:
			frappe.log_error(
				title="Demand Loan Demand Generation Error",
				message=frappe.get_traceback(),
				reference_doctype="Loan",
				reference_name=loan,
			)


def make_loan_demand_for_demand_loan(posting_date, loan, process_loan_demand):
	# get last demand date
	loan_demands = frappe.qb.DocType("Loan Demand")
	query = (
		frappe.qb.from_(loan_demands)
		.select(loan_demands.demand_date)
		.where(loan_demands.docstatus == 1)
		.where(loan_demands.loan == loan)
		.where(loan_demands.demand_date <= posting_date)
		.orderby(loan_demands.demand_date, order=frappe.qb.desc)
		.limit(1)
	)

	last_demand_date = query.run()
	if len(last_demand_date):
		last_demand_date = last_demand_date[0][0]
	else:
		last_demand_date = None

	interest_accruals = frappe.qb.DocType("Loan Interest Accrual")
	query = (
		frappe.qb.from_(interest_accruals)
		.select(frappe.query_builder.functions.Sum(interest_accruals.interest_amount))
		.where(interest_accruals.docstatus == 1)
		.where(interest_accruals.loan == loan)
	)
	if last_demand_date:
		query = query.where(interest_accruals.posting_date > last_demand_date)

	total_pending_interest = query.run()
	if len(total_pending_interest):
		total_pending_interest = total_pending_interest[0][0]
	else:
		total_pending_interest = 0

	create_loan_demand(
		loan,
		posting_date,
		"Normal",
		"Interest",
		total_pending_interest,
		process_loan_demand=process_loan_demand,
	)


def get_batches(open_loans, batch_size):
	for i in range(0, len(open_loans), batch_size):
		yield open_loans[i : i + batch_size]


def get_open_loans(is_term_loan, loan_product=None, loan=None):
	filters = {
		"docstatus": 1,
		"status": ("in", ("Disbursed", "Partially Disbursed", "Active")),
		"is_term_loan": is_term_loan,
	}

	or_filters = {}

	if is_term_loan:
		or_filters = {
			"excess_amount_paid": ("<=", 0),
			"repayment_schedule_type": "Line of Credit",
		}

	if loan_product:
		filters["loan_product"] = loan_product

	if loan:
		filters["name"] = loan

	return frappe.db.get_all(
		"Loan", filters=filters, or_filters=or_filters, pluck="name", order_by="applicant"
	)


def create_loan_demand(
	loan,
	demand_date,
	demand_type,
	demand_subtype,
	amount,
	loan_repayment_schedule=None,
	loan_disbursement=None,
	repayment_schedule_detail=None,
	sales_invoice=None,
	process_loan_demand=None,
	paid_amount=0,
	posting_date=None,
	loan_repayment=None,
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2
	if amount:
		demand = frappe.new_doc("Loan Demand")
		demand.loan = loan
		demand.loan_repayment_schedule = loan_repayment_schedule
		demand.loan_disbursement = loan_disbursement
		demand.repayment_schedule_detail = repayment_schedule_detail
		demand.demand_date = demand_date
		demand.posting_date = posting_date
		demand.demand_type = demand_type
		demand.demand_subtype = demand_subtype
		demand.demand_amount = flt(amount, precision)
		demand.sales_invoice = sales_invoice
		demand.process_loan_demand = process_loan_demand
		demand.paid_amount = paid_amount
		demand.loan_repayment = loan_repayment
		demand.save()
		demand.submit()


def reverse_demands(
	loan,
	posting_date,
	demand_type=None,
	loan_repayment_schedule=None,
	loan_disbursement=None,
	on_settlement_or_closure=False,
	future_demands=False,
	loan_repayment=None,
):

	# on settlement or closure, demand should be cleared from next day
	# as other demands also get passed on the same day
	if on_settlement_or_closure:
		posting_date = add_days(posting_date, 1)

	filters = {"loan": loan, "demand_date": (">=", posting_date), "docstatus": 1}
	or_filters = {}

	if loan_repayment:
		filters["loan_repayment"] = loan_repayment

	if demand_type:
		filters["demand_type"] = demand_type

	if demand_type == "Penalty":
		filters["demand_type"] = ("in", ("Penalty", "Additional Interest"))

	if loan_repayment_schedule and not future_demands:
		filters["loan_repayment_schedule"] = loan_repayment_schedule
	elif loan_repayment_schedule and future_demands:
		or_filters["loan_repayment_schedule"] = loan_repayment_schedule
		or_filters["demand_date"] = (">", posting_date)
		del filters["demand_date"]

	if loan_disbursement:
		filters["loan_disbursement"] = loan_disbursement

	for demand in frappe.get_all("Loan Demand", filters=filters, or_filters=or_filters):
		doc = frappe.get_doc("Loan Demand", demand.name)
		doc.flags.ignore_links = True
		doc.cancel()


def make_credit_note(
	company,
	item_code,
	applicant,
	loan,
	sales_invoice,
	demand_date,
	amount=0,
	loan_repayment=None,
	waiver_account=None,
	posting_date=None,
):
	si = frappe.new_doc("Sales Invoice")
	si.flags.ignore_links = True
	si.company = company
	si.customer = applicant
	si.loan = loan
	si.is_return = 1
	si.return_against = sales_invoice
	si.update_outstanding_for_self = 0
	si.loan_repayment = loan_repayment

	if not posting_date:
		posting_date = getdate()

		if posting_date < getdate(demand_date):
			posting_date = demand_date

	si.set_posting_time = 1
	si.posting_date = posting_date

	rate, income_account = frappe.db.get_value(
		"Sales Invoice Item",
		{"item_code": item_code, "parent": sales_invoice},
		["rate", "income_account"],
	)

	si.append(
		"items",
		{
			"item_code": item_code,
			"qty": -1,
			"rate": amount or rate,
			"income_account": waiver_account or income_account,
		},
	)

	si.save()
	si.submit()

	return si


def get_freeze_date_map(loans):
	return frappe._dict(
		frappe.db.get_all(
			"Loan", filters={"name": ("in", loans)}, fields=["name", "freeze_date"], as_list=1
		)
	)
