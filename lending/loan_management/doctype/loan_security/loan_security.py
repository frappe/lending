# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)
from lending.loan_management.doctype.loan_security_type.loan_security_type import (
	validate_haircut_and_ltv,
)


class LoanSecurity(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		available_security_value: DF.Currency
		disabled: DF.Check
		haircut: DF.Percent
		loan_security_code: DF.Data
		loan_security_name: DF.Data
		loan_security_type: DF.Link
		loan_to_value_ratio: DF.Percent
		original_security_value: DF.Currency
		utilized_security_value: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.update_available_security_value()
		validate_haircut_and_ltv(self)
		self.warn_if_running_loans_go_into_shortfall()

	def update_available_security_value(self):
		self.available_security_value = flt(self.original_security_value) - flt(
			self.utilized_security_value
		)

	def warn_if_running_loans_go_into_shortfall(self):
		from lending.loan_management.doctype.loan_security_release.loan_security_release import (
			get_pledged_security_qty,
		)
		from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
			LOAN_OUTSTANDING_FIELDS,
			get_current_price_map,
			get_loan_shortfall,
			get_ltv_ratio_map,
		)

		doc_before_save = self.get_doc_before_save()
		if not doc_before_save:
			return

		old_ltv = flt(doc_before_save.loan_to_value_ratio)
		if flt(self.loan_to_value_ratio) >= old_ltv:
			return

		if not frappe.has_permission("Loan", "read"):
			return

		loan_names = self.get_loans_with_this_security()
		if not loan_names:
			return

		# get_list, not get_all: the user only sees loans they may read
		loans = frappe.get_list(
			"Loan",
			fields=LOAN_OUTSTANDING_FIELDS,
			filters={
				"name": ("in", loan_names),
				"status": ("in", ["Disbursed", "Partially Disbursed"]),
				"is_secured_loan": 1,
			},
		)
		if not loans:
			return

		pledges_by_loan = {loan.name: get_pledged_security_qty(loan=loan.name) for loan in loans}
		securities = list({security for pledges in pledges_by_loan.values() for security in pledges})
		price_map = get_current_price_map(securities)
		old_ltv_map = get_ltv_ratio_map(securities)
		new_ltv_map = {**old_ltv_map, self.name: self.loan_to_value_ratio}

		def is_short(loan, ltv_map):
			_outstanding, security_value, shortfall_amount = get_loan_shortfall(
				loan, pledges_by_loan[loan.name], price_map, ltv_map
			)
			return security_value and flt(shortfall_amount, 6) > 0

		newly_short = [
			loan.name for loan in loans if is_short(loan, new_ltv_map) and not is_short(loan, old_ltv_map)
		]
		if not newly_short:
			return

		frappe.msgprint(
			_(
				"Lowering the Loan To Value Ratio from {0}% to {1}% puts these running loans into "
				"shortfall at the next shortfall check: {2}"
			).format(
				old_ltv,
				flt(self.loan_to_value_ratio),
				", ".join(frappe.bold(loan) for loan in newly_short),
			),
			title=_("Running Loans Affected"),
			indicator="orange",
		)

	def get_loans_with_this_security(self):
		pledge = frappe.qb.DocType("Pledge")
		assignment = frappe.qb.DocType("Loan Security Assignment")

		return (
			frappe.qb.from_(pledge)
			.inner_join(assignment)
			.on(pledge.parent == assignment.name)
			.select(assignment.loan)
			.distinct()
			.where(pledge.loan_security == self.name)
			.where(assignment.docstatus == 1)
			.where(assignment.status == "Pledged")
			.where(assignment.loan.isnotnull())
			.run(pluck=True)
		)


@frappe.whitelist()
def get_loan_security_price_or_value(loan_security: str):
	loan_security_price = get_loan_security_price(loan_security)

	if loan_security_price:
		return {"qty": None, "value": loan_security_price}

	return {
		"qty": 1,
		"value": frappe.db.get_value("Loan Security", loan_security, "available_security_value"),
	}

def get_haircut_percentage(loan_security):
	haircut = frappe.db.get_value("Loan Security", loan_security, "haircut")

	if not haircut:
		loan_security_type = frappe.db.get_value("Loan Security", loan_security, "loan_security_type")
		haircut = frappe.db.get_value("Loan Security Type", loan_security_type, "haircut")

	return haircut
