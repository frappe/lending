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
		applicant: DF.Data
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		company: DF.Link
		description: DF.Text | None
		loan: DF.Link | None
		reference_no: DF.Data | None
		securities: DF.Table[Unpledge]
		status: DF.Literal["Requested", "Approved"]
		unpledge_time: DF.Datetime | None
	# end: auto-generated types

	def validate(self):
		self.validate_duplicate_securities()
		self.validate_unpledge_qty()

	def on_cancel(self):
		self.update_loan_status(cancel=1)
		self.db_set("status", "Requested")

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
			self.update_sanctioned_loan_amount()

	def update_sanctioned_loan_amount(self):
		from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
			get_ltv_ratio,
		)

		current_pledged_qty = get_pledged_security_qty(applicant=self.applicant)
		securities = list(current_pledged_qty)
		loan_security_price_map = get_loan_security_price_map(securities)

		new_sanctioned_loan_amount = 0
		for security, qty in current_pledged_qty.items():
			current_price = flt(loan_security_price_map.get(security))
			new_sanctioned_loan_amount += (qty * current_price * get_ltv_ratio(security)) / 100

		if new_sanctioned_loan_amount > 0:
			frappe.db.set_value("Sanctioned Loan Amount", {
				"applicant": self.applicant,
				"applicant_type": self.applicant_type
			}, "sanctioned_amount_limit", new_sanctioned_loan_amount)


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


@frappe.whitelist()
def get_pledged_security_qty(loan: str | None = None, applicant: str | None = None):
	current_pledges = {}

	unpldge_doctype = frappe.qb.DocType("Unpledge")
	loan_security_release_doctype = frappe.qb.DocType("Loan Security Release")

	pledge_doctype = frappe.qb.DocType("Pledge")
	loan_security_assignment_doctype = frappe.qb.DocType("Loan Security Assignment")

	unpledge_query = frappe.qb.from_(unpldge_doctype).inner_join(loan_security_release_doctype).on(
		unpldge_doctype.parent == loan_security_release_doctype.name
	).select(
		unpldge_doctype.loan_security, fn.Sum(unpldge_doctype.qty).as_("qty")
	).where(loan_security_release_doctype.docstatus == 1).where(loan_security_release_doctype.status == "Approved")

	pledge_query = frappe.qb.from_(pledge_doctype).inner_join(loan_security_assignment_doctype).on(
		pledge_doctype.parent == loan_security_assignment_doctype.name
	).select(
		pledge_doctype.loan_security, fn.Sum(pledge_doctype.qty).as_("qty")
	).where(loan_security_assignment_doctype.docstatus == 1).where(loan_security_assignment_doctype.status == "Pledged")

	if loan:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.loan == loan)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.loan == loan)

	if applicant:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.applicant == applicant)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.applicant == applicant)

	unpledges = frappe._dict(unpledge_query.groupby(unpldge_doctype.loan_security).run())
	pledges = frappe._dict(pledge_query.groupby(pledge_doctype.loan_security).run())

	for security, qty in pledges.items():
		current_pledges.setdefault(security, qty)
		current_pledges[security] -= unpledges.get(security, 0.0)

	return current_pledges
