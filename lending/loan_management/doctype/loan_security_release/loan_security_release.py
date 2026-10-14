# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.model.document import Document
from frappe.query_builder import functions as fn
from frappe.utils import comma_and, flt, get_datetime, getdate

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
		self.allocate_to_assignments()
		self.validate_duplicate_securities()
		self.validate_unpledge_qty()
		self.validate_release_references()

	def allocate_to_assignments(self):
		# Each row names the pledge it frees, so that pledge cannot be cancelled while this
		# release still subtracts its shares. A row left blank takes the oldest pledges of that
		# security first, split into one row per pledge where needed.
		candidates = self.get_candidate_assignments()
		unreleased = get_unreleased_qty(candidates, exclude_release=self.name, for_update=True)

		for row in self.securities:
			if not row.loan_security_assignment:
				continue

			key = (row.loan_security_assignment, row.loan_security)
			if key not in unreleased:
				message = (
					_("Row {0}: {1} is not a pledge of {2} by {3} on Loan {4}.")
					if self.loan
					else _("Row {0}: {1} is not a pledge of {2} by {3}.")
				)
				frappe.throw(
					message.format(
						row.idx,
						frappe.bold(row.loan_security_assignment),
						frappe.bold(row.loan_security),
						frappe.bold(self.applicant),
						frappe.bold(self.loan),
					)
				)
			if flt(row.qty) > flt(unreleased[key]):
				frappe.throw(
					_("Row {0}: only {1} of {2} on {3} is not yet released.").format(
						row.idx,
						flt(unreleased[key]),
						frappe.bold(row.loan_security),
						frappe.bold(row.loan_security_assignment),
					),
					title=_("Already Released"),
				)
			unreleased[key] -= flt(row.qty)

		if all(row.loan_security_assignment for row in self.securities):
			return

		fields = get_unpledge_fields()
		rows = []
		for row in self.securities:
			values = {field: row.get(field) for field in fields}
			if row.loan_security_assignment:
				rows.append(values)
				continue

			remaining = flt(row.qty)
			for name in candidates:
				free = flt(unreleased.get((name, row.loan_security)))
				if remaining <= 0:
					break
				if free <= 0:
					continue

				qty = min(free, remaining)
				rows.append({**values, "qty": qty, "loan_security_assignment": name})
				unreleased[(name, row.loan_security)] -= qty
				remaining -= qty

			if remaining > 0:
				message = (
					_(
						"Row {0}: only {1} of {2} is pledged by {3} on Loan {5} and not yet released. You are trying to release {4}."
					)
					if self.loan
					else _(
						"Row {0}: only {1} of {2} is pledged by {3} and not yet released. You are trying to release {4}."
					)
				)
				frappe.throw(
					message.format(
						row.idx,
						flt(row.qty) - remaining,
						frappe.bold(row.loan_security),
						frappe.bold(self.applicant),
						flt(row.qty),
						frappe.bold(self.loan),
					),
					title=_("Loan Security Release Error"),
				)

		self.set("securities", [])
		for row in rows:
			self.append("securities", row)

	def get_candidate_assignments(self):
		filters = {"docstatus": 1, "status": "Pledged"}
		if self.loan:
			filters["loan"] = self.loan
		else:
			filters.update({"applicant_type": self.applicant_type, "applicant": self.applicant})

		return frappe.get_all(
			"Loan Security Assignment", filters=filters, order_by="pledge_time asc, creation asc", pluck="name"
		)

	def before_update_after_submit(self):
		# Approval changes the status on a submitted release, which skips validate.
		self.validate_release_references()

	def validate_release_references(self):
		if self.status == "Approved":
			validate_references(
				self.securities,
				"release_reference",
				_("Add the release reference for {0} before approving the release."),
				_("Release Reference Missing"),
			)

	def on_cancel(self):
		self.update_loan_status(cancel=1)
		self.db_set("status", "Requested")
		update_sanctioned_loan_amount_for_applicant(self.applicant, self.applicant_type)

	def validate_duplicate_securities(self):
		seen = set()
		for d in self.securities:
			key = (d.loan_security, d.loan_security_assignment)
			if key in seen:
				frappe.throw(
					_("Row {0}: Loan Security {1} added multiple times").format(
						d.idx, frappe.bold(d.loan_security)
					)
				)
			seen.add(key)

	def validate_unpledge_qty(self):
		from lending.loan_management.doctype.loan_repayment.loan_repayment import (
			get_pending_principal_amount,
		)
		from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
			get_ltv_ratio,
		)

		pledge_qty_map = get_pledged_security_qty(loan=self.loan, applicant=self.applicant)
		securities = list(pledge_qty_map)
		loan_security_price_map = get_loan_security_price_map(securities)

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
			unpledge_qty_map = {}
			ltv_ratio = 0

			for security in self.securities:
				pledged_qty = pledge_qty_map.get(security.loan_security, 0)
				if security.qty > pledged_qty:
					msg = _("Row {0}: {1} of {2} is pledged against Loan {3}.").format(
						security.idx,
						pledged_qty,
						frappe.bold(security.loan_security),
						frappe.bold(self.loan),
					)
					msg += "<br>"
					msg += _("You are trying to unpledge more.")
					frappe.throw(msg, title=_("Loan Security Release Error"))

				unpledge_qty_map.setdefault(security.loan_security, 0)
				unpledge_qty_map[security.loan_security] += security.qty

			for security in pledge_qty_map:
				if not ltv_ratio:
					ltv_ratio = get_ltv_ratio(security)

				qty_after_unpledge = pledge_qty_map.get(security, 0) - unpledge_qty_map.get(security, 0)
				current_price = loan_security_price_map.get(security)

				if not current_price:
					current_price = frappe.db.get_value(
						"Pledge", {"loan_security": security}, "loan_security_price"
					)

				security_value += qty_after_unpledge * current_price

			if not security_value and flt(pending_principal_amount, 2) > 0:
				self._throw(security_value, pending_principal_amount, ltv_ratio)

			if security_value and flt(pending_principal_amount / security_value) * 100 > ltv_ratio:
				self._throw(security_value, pending_principal_amount, ltv_ratio)

	def _throw(self, security_value, pending_principal_amount, ltv_ratio):
		msg = _("Loan Security Value after unpledge is {0}").format(frappe.bold(security_value))
		msg += "<br>"
		msg += _("Pending principal amount for loan {0} is {1}").format(
			frappe.bold(self.loan), frappe.bold(flt(pending_principal_amount, 2))
		)
		msg += "<br>"
		msg += _("Loan To Security Value ratio must always be {0}").format(frappe.bold(ltv_ratio))
		frappe.throw(msg, title=_("Loan To Value ratio breach"))

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
		get_ltv_ratio,
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

	if current_pledged_qty:
		loan_security_price_map = get_loan_security_price_map(list(current_pledged_qty))

	new_sanctioned_loan_amount = 0
	for security, qty in current_pledged_qty.items():
		current_price = flt(loan_security_price_map.get(security))
		new_sanctioned_loan_amount += (flt(qty) * current_price * flt(get_ltv_ratio(security))) / 100

	frappe.db.set_value(
		"Sanctioned Loan Amount",
		sanctioned_limit,
		"sanctioned_amount_limit",
		new_sanctioned_loan_amount,
	)


def validate_references(securities, fieldname, message, title):
	missing = [row.get("loan_security") for row in securities if not (row.get(fieldname) or "").strip()]
	if missing:
		frappe.throw(message.format(comma_and(missing)), title=title)


def get_unpledge_fields():
	return [
		df.fieldname for df in frappe.get_meta("Unpledge").fields if df.fieldtype not in no_value_fields
	]


def get_unreleased_qty(assignments, exclude_release=None, for_update=False):
	"""Return {(assignment, loan_security): qty} still to be released on each assignment.

	A submitted release that is not yet approved already claims its quantity, so two
	releases cannot both be made for the same shares.
	"""
	if not assignments:
		return {}

	pledge = frappe.qb.DocType("Pledge")
	unpledge = frappe.qb.DocType("Unpledge")
	release = frappe.qb.DocType("Loan Security Release")

	pledged_query = (
		frappe.qb.from_(pledge)
		.select(pledge.parent, pledge.loan_security, fn.Sum(pledge.qty))
		.where(pledge.parenttype == "Loan Security Assignment")
		.where(pledge.parent.isin(assignments))
		.groupby(pledge.parent, pledge.loan_security)
	)
	released_query = (
		frappe.qb.from_(unpledge)
		.inner_join(release)
		.on(unpledge.parent == release.name)
		.select(unpledge.loan_security_assignment, unpledge.loan_security, fn.Sum(unpledge.qty))
		.where(release.docstatus == 1)
		.where(unpledge.loan_security_assignment.isin(assignments))
		.groupby(unpledge.loan_security_assignment, unpledge.loan_security)
	)
	if exclude_release:
		released_query = released_query.where(release.name != exclude_release)
	if for_update:
		pledged_query = pledged_query.for_update()
		released_query = released_query.for_update()

	released = {(name, security): flt(qty) for name, security, qty in released_query.run()}
	return {
		(name, security): flt(qty) - released.get((name, security), 0.0)
		for name, security, qty in pledged_query.run()
	}


@frappe.whitelist()
def get_pledged_security_qty(loan: str | None = None, applicant: str | None = None):
	if loan:
		frappe.has_permission("Loan", "read", doc=loan, throw=True)
	else:
		frappe.has_permission("Loan", "read", throw=True)

	return get_pledged_qty_map(loan=loan, applicant=applicant)


def get_pledged_qty_map(loan=None, applicant=None, securities=None, for_update=False):
	current_pledges = {}

	unpldge_doctype = frappe.qb.DocType("Unpledge")
	loan_security_release_doctype = frappe.qb.DocType("Loan Security Release")

	pledge_doctype = frappe.qb.DocType("Pledge")
	loan_security_assignment_doctype = frappe.qb.DocType("Loan Security Assignment")

	unpledge_query = frappe.qb.from_(unpldge_doctype).inner_join(loan_security_release_doctype).on(
		unpldge_doctype.parent == loan_security_release_doctype.name
	).select(
		loan_security_release_doctype.applicant_type,
		loan_security_release_doctype.applicant,
		unpldge_doctype.loan_security,
		fn.Sum(unpldge_doctype.qty).as_("qty"),
	).where(loan_security_release_doctype.docstatus == 1).where(loan_security_release_doctype.status == "Approved")

	pledge_query = frappe.qb.from_(pledge_doctype).inner_join(loan_security_assignment_doctype).on(
		pledge_doctype.parent == loan_security_assignment_doctype.name
	).select(
		loan_security_assignment_doctype.applicant_type,
		loan_security_assignment_doctype.applicant,
		pledge_doctype.loan_security,
		fn.Sum(pledge_doctype.qty).as_("qty"),
	).where(loan_security_assignment_doctype.docstatus == 1).where(loan_security_assignment_doctype.status == "Pledged")

	if loan:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.loan == loan)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.loan == loan)

	if applicant:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.applicant == applicant)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.applicant == applicant)

	if securities:
		unpledge_query = unpledge_query.where(unpldge_doctype.loan_security.isin(securities))
		pledge_query = pledge_query.where(pledge_doctype.loan_security.isin(securities))

	if for_update:
		# A locking read sees the latest committed pledges, not this transaction's snapshot.
		unpledge_query = unpledge_query.for_update()
		pledge_query = pledge_query.for_update()

	unpledges = unpledge_query.groupby(
		loan_security_release_doctype.applicant_type,
		loan_security_release_doctype.applicant,
		unpldge_doctype.loan_security,
	).run()
	pledges = pledge_query.groupby(
		loan_security_assignment_doctype.applicant_type,
		loan_security_assignment_doctype.applicant,
		pledge_doctype.loan_security,
	).run()

	# Net releases against the same applicant's pledges, so releases left over from a
	# cancelled or already released assignment cannot hide another applicant's pledge.
	released = {(applicant_type, applicant, security): qty for applicant_type, applicant, security, qty in unpledges}
	for applicant_type, applicant, security, qty in pledges:
		remaining = flt(qty) - flt(released.get((applicant_type, applicant, security)))
		current_pledges[security] = current_pledges.get(security, 0.0) + max(remaining, 0.0)

	return current_pledges
