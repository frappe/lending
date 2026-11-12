# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import functions as fn
from frappe.utils import flt, get_datetime, getdate

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price_map,
)


class LoanSecurityRelease(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.unpledge.unpledge import Unpledge

		amended_from: DF.Link | None
		applicant: DF.DynamicLink
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		company: DF.Link
		description: DF.Text | None
		loan: DF.Link | None
		reference_no: DF.Data | None
		securities: DF.Table[Unpledge]
		status: DF.Literal["Requested", "Approved"]
		unpledge_time: DF.Datetime | None
	# end: auto-generated types

	def save(self, *args, **kwargs):
		# Saving locks this release's row before any hook runs, and approving the final release
		# writes the Loan. Lock the Loan first, in the same order as a top-up pledge, so the
		# two cannot deadlock.
		if self.loan:
			frappe.db.get_value("Loan", self.loan, "name", for_update=True)

		return super().save(*args, **kwargs)

	def validate(self):
		self.validate_duplicate_securities()
		self.validate_unpledge_qty()

	def before_submit(self):
		# An amendment copies the cancelled release's time, which would skip approve().
		self.unpledge_time = None
		self.validate_qty_still_pledged()

	def validate_qty_still_pledged(self):
		# Holds the applicant lock that a pledge cancel also takes, so the two cannot free the same shares.
		if self.status != "Approved" or self.unpledge_time:
			return

		lock_applicant(self.applicant_type, self.applicant)
		pledge_qty_map = get_current_pledges(loan=self.loan, applicant=self.applicant, for_update=True)

		for security in self.securities:
			pledged_qty = flt(pledge_qty_map.get(security.loan_security))
			if security.qty > pledged_qty:
				frappe.throw(
					_("Row {0}: Only {1} of {2} is still pledged.").format(
						security.idx, pledged_qty, frappe.bold(security.loan_security)
					),
					title=_("Loan Security Release Error"),
				)

	def on_cancel(self):
		self.update_loan_status(cancel=1)
		self.db_set("status", "Requested")
		update_sanctioned_loan_amount_for_applicant(self.applicant, self.applicant_type)

	def validate_duplicate_securities(self):
		security_list = []
		for d in self.securities:
			if d.loan_security not in security_list:
				security_list.append(d.loan_security)
			else:
				frappe.throw(
					_("Row {0}: Loan Security {1} added multiple times").format(
						d.idx, frappe.bold(d.loan_security)
					)
				)

	def validate_unpledge_qty(self, for_update=False):
		from lending.loan_management.doctype.loan_repayment.loan_repayment import (
			get_pending_principal_amount,
		)
		from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
			get_ltv_ratio_map,
		)

		if for_update:
			pledge_qty_map = get_current_pledges(loan=self.loan, applicant=self.applicant, for_update=True)
		else:
			pledge_qty_map = get_pledged_security_qty(loan=self.loan, applicant=self.applicant)
		securities = list(pledge_qty_map)
		loan_security_price_map = get_loan_security_price_map(securities)
		ltv_ratio_map = get_ltv_ratio_map(securities)

		unpledge_qty_map = {}
		for security in self.securities:
			pledged_qty = pledge_qty_map.get(security.loan_security, 0)
			if security.qty > pledged_qty:
				if self.loan:
					msg = _("Row {0}: {1} of {2} is pledged against Loan {3}.").format(
						security.idx,
						pledged_qty,
						frappe.bold(security.loan_security),
						frappe.bold(self.loan),
					)
				else:
					msg = _("Row {0}: {1} of {2} is pledged by {3}.").format(
						security.idx,
						pledged_qty,
						frappe.bold(security.loan_security),
						frappe.bold(self.applicant),
					)
				msg += "<br>"
				msg += _("You are trying to unpledge more.")
				frappe.throw(msg, title=_("Loan Security Release Error"))

			unpledge_qty_map.setdefault(security.loan_security, 0)
			unpledge_qty_map[security.loan_security] += security.qty

		if self.loan:
			loan_details = frappe.get_value(
				"Loan",
				self.loan,
				[
					"total_payment",
					"debit_adjustment_amount",
					"credit_adjustment_amount",
					"refund_amount",
					"total_principal_paid",
					"loan_amount",
					"total_interest_payable",
					"written_off_amount",
					"disbursed_amount",
					"status",
				],
				as_dict=1,
			)

			pending_principal_amount = get_pending_principal_amount(loan_details)

			security_value = 0
			allowed_amount = 0
			for security in pledge_qty_map:
				qty_after_unpledge = pledge_qty_map.get(security, 0) - unpledge_qty_map.get(security, 0)
				value = qty_after_unpledge * flt(loan_security_price_map.get(security))
				security_value += value
				allowed_amount += value * flt(ltv_ratio_map.get(security)) / 100

			if flt(pending_principal_amount, 2) > flt(allowed_amount, 2):
				self._throw(security_value, pending_principal_amount, allowed_amount)

	def _throw(self, security_value, pending_principal_amount, allowed_amount):
		msg = _("Loan Security Value after unpledge is {0}").format(frappe.bold(security_value))
		msg += "<br>"
		msg += _("Pending principal amount for loan {0} is {1}").format(
			frappe.bold(self.loan), frappe.bold(flt(pending_principal_amount, 2))
		)
		msg += "<br>"
		msg += _("Maximum loan allowed against the remaining securities is {0}").format(
			frappe.bold(flt(allowed_amount, 2))
		)
		frappe.throw(msg, title=_("Loan To Value ratio breach"))

	def before_update_after_submit(self):
		# Approval is what consumes the collateral, so recheck it under the lock a Loan Security Sale takes
		if self.status == "Approved" and self.has_value_changed("status"):
			if self.loan:
				frappe.db.get_value("Loan", self.loan, "name", for_update=True)
			self.validate_unpledge_qty(for_update=bool(self.loan))

		self.validate_qty_still_pledged()

	def on_update_after_submit(self):
		self.approve()

	def approve(self):
		if self.status == "Approved" and not self.unpledge_time:
			if self.loan:
				self.update_loan_status()

			self.db_set("unpledge_time", get_datetime())
			update_sanctioned_loan_amount_for_applicant(self.applicant, self.applicant_type)

	def update_loan_status(self, cancel=0):
		if cancel:
			loan_status = frappe.get_value("Loan", self.loan, "status")
			if loan_status == "Closed":
				frappe.db.set_value("Loan", self.loan, "status", "Loan Closure Requested")
		else:
			pledged_qty = 0
			current_pledges = get_pledged_security_qty(loan=self.loan)

			for security, qty in current_pledges.items():
				pledged_qty += qty

			if not pledged_qty:
				frappe.db.set_value("Loan", self.loan, {"status": "Closed", "closure_date": getdate()})


def update_sanctioned_loan_amount_for_applicant(applicant, applicant_type):
	from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
		get_ltv_ratio_map,
	)

	if not applicant or not applicant_type:
		return

	sanctioned_limit = frappe.db.get_value(
		"Sanctioned Loan Amount",
		{"applicant": applicant, "applicant_type": applicant_type},
		"name",
	)

	if not sanctioned_limit:
		return

	current_pledged_qty = get_pledged_security_qty(applicant=applicant)
	loan_security_price_map = {}
	ltv_ratio_map = {}

	if current_pledged_qty:
		loan_security_price_map = get_loan_security_price_map(list(current_pledged_qty))
		ltv_ratio_map = get_ltv_ratio_map(list(current_pledged_qty))

	new_sanctioned_loan_amount = 0
	for security, qty in current_pledged_qty.items():
		current_price = flt(loan_security_price_map.get(security))
		new_sanctioned_loan_amount += (flt(qty) * current_price * flt(ltv_ratio_map.get(security))) / 100

	frappe.db.set_value(
		"Sanctioned Loan Amount",
		sanctioned_limit,
		"sanctioned_amount_limit",
		new_sanctioned_loan_amount,
	)


@frappe.whitelist()
def get_pledged_security_qty(loan: str | None = None, applicant: str | None = None):
	if loan:
		frappe.has_permission("Loan", "read", doc=loan, throw=True)
	else:
		frappe.has_permission("Loan", "read", throw=True)

	return get_current_pledges(loan=loan, applicant=applicant)


def lock_applicant(applicant_type, applicant):
	frappe.db.get_value(applicant_type, applicant, "name", for_update=True)


def get_current_pledges_by_loan(loans):
	# {loan: {security: qty}} for many loans in three queries, netted as get_current_pledges does
	return get_current_pledges(loan=loans, by_loan=True) if loans else {}


def get_current_pledges(
	loan=None,
	applicant=None,
	securities=None,
	for_update=False,
	by_loan=False,
	company=None,
	by_applicant=False,
):
	current_pledges = {}

	unpldge_doctype = frappe.qb.DocType("Unpledge")
	loan_security_release_doctype = frappe.qb.DocType("Loan Security Release")

	pledge_doctype = frappe.qb.DocType("Pledge")
	loan_security_assignment_doctype = frappe.qb.DocType("Loan Security Assignment")

	def loan_field(doctype):
		return [doctype.loan] if by_loan else []

	unpledge_query = frappe.qb.from_(unpldge_doctype).inner_join(loan_security_release_doctype).on(
		unpldge_doctype.parent == loan_security_release_doctype.name
	).select(
		*loan_field(loan_security_release_doctype),
		loan_security_release_doctype.applicant_type,
		loan_security_release_doctype.applicant,
		unpldge_doctype.loan_security,
		fn.Sum(unpldge_doctype.qty).as_("qty"),
	).where(loan_security_release_doctype.docstatus == 1).where(loan_security_release_doctype.status == "Approved")

	pledge_query = frappe.qb.from_(pledge_doctype).inner_join(loan_security_assignment_doctype).on(
		pledge_doctype.parent == loan_security_assignment_doctype.name
	).select(
		*loan_field(loan_security_assignment_doctype),
		loan_security_assignment_doctype.applicant_type,
		loan_security_assignment_doctype.applicant,
		pledge_doctype.loan_security,
		fn.Sum(pledge_doctype.qty).as_("qty"),
	).where(loan_security_assignment_doctype.docstatus == 1).where(
		# A Repossessed assignment's pledges stay counted so that the sales which emptied it net them out
		loan_security_assignment_doctype.status.isin(["Pledged", "Repossessed"])
	)

	sale_item_doctype = frappe.qb.DocType("Loan Security Sale Item")
	sale_doctype = frappe.qb.DocType("Loan Security Sale")

	sale_query = frappe.qb.from_(sale_item_doctype).inner_join(sale_doctype).on(
		sale_item_doctype.parent == sale_doctype.name
	).select(
		*loan_field(sale_doctype),
		sale_doctype.applicant_type,
		sale_doctype.applicant,
		sale_item_doctype.loan_security,
		fn.Sum(sale_item_doctype.sold_qty).as_("qty"),
	).where(sale_doctype.docstatus == 1)

	if isinstance(loan, list | tuple | set):
		unpledge_query = unpledge_query.where(loan_security_release_doctype.loan.isin(list(loan)))
		pledge_query = pledge_query.where(loan_security_assignment_doctype.loan.isin(list(loan)))
		sale_query = sale_query.where(sale_doctype.loan.isin(list(loan)))
	elif loan:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.loan == loan)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.loan == loan)
		sale_query = sale_query.where(sale_doctype.loan == loan)

	if applicant:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.applicant == applicant)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.applicant == applicant)
		sale_query = sale_query.where(sale_doctype.applicant == applicant)

	if securities:
		unpledge_query = unpledge_query.where(unpldge_doctype.loan_security.isin(securities))
		pledge_query = pledge_query.where(pledge_doctype.loan_security.isin(securities))
		sale_query = sale_query.where(sale_item_doctype.loan_security.isin(securities))

	if company:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.company == company)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.company == company)
		sale_query = sale_query.where(sale_doctype.company == company)

	if for_update:
		# A locking read sees the latest committed pledges, not this transaction's snapshot.
		unpledge_query = unpledge_query.for_update()
		pledge_query = pledge_query.for_update()
		sale_query = sale_query.for_update()

	unpledges = unpledge_query.groupby(
		*loan_field(loan_security_release_doctype),
		loan_security_release_doctype.applicant_type,
		loan_security_release_doctype.applicant,
		unpldge_doctype.loan_security,
	).run()
	pledges = pledge_query.groupby(
		*loan_field(loan_security_assignment_doctype),
		loan_security_assignment_doctype.applicant_type,
		loan_security_assignment_doctype.applicant,
		pledge_doctype.loan_security,
	).run()
	sales = sale_query.groupby(
		*loan_field(sale_doctype),
		sale_doctype.applicant_type,
		sale_doctype.applicant,
		sale_item_doctype.loan_security,
	).run()

	# Net releases and sales against the same applicant's pledges, so releases left over from a
	# cancelled or already released assignment cannot hide another applicant's pledge.
	# Each row is ([loan,] applicant_type, applicant, security, qty).
	taken_out = {}
	for *key, qty in (*unpledges, *sales):
		taken_out[tuple(key)] = taken_out.get(tuple(key), 0.0) + flt(qty)

	for *key, qty in pledges:
		remaining = max(flt(qty) - taken_out.get(tuple(key), 0.0), 0.0)
		if by_applicant:
			# Keyed (applicant_type, applicant, security)
			current_pledges[tuple(key[-3:])] = current_pledges.get(tuple(key[-3:]), 0.0) + remaining
			continue
		security = key[-1]
		pledged = current_pledges.setdefault(key[0], {}) if by_loan else current_pledges
		pledged[security] = pledged.get(security, 0.0) + remaining

	return current_pledges
