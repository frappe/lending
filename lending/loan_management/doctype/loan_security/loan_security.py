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
		from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
			get_current_price_map,
			get_ltv_ratio_map,
		)

		doc_before_save = self.get_doc_before_save()
		if not doc_before_save:
			return

		old_ltv = flt(doc_before_save.loan_to_value_ratio)
		if flt(self.loan_to_value_ratio) >= old_ltv or not frappe.has_permission("Loan", "read"):
			return

		assignments = self.get_assignments_with_this_security()
		if not assignments:
			return

		pledges_by_loan = self.get_pledges_by_running_loan({row.loan for row in assignments if row.loan})
		pledges_by_customer = self.get_pledges_by_customer(
			{row.applicant for row in assignments if row.applicant_type == "Customer"}
		)

		all_pledges = [pledges for _loan, pledges in pledges_by_loan] + list(pledges_by_customer.values())
		securities = list({security for pledges in all_pledges for security in pledges})
		price_map = get_current_price_map(securities)
		old_ltv_map = get_ltv_ratio_map(securities)
		new_ltv_map = {**old_ltv_map, self.name: self.loan_to_value_ratio}

		newly_short_loans = get_newly_short_loans(pledges_by_loan, price_map, old_ltv_map, new_ltv_map)
		newly_short_customers = get_newly_short_customers(
			pledges_by_customer, price_map, old_ltv_map, new_ltv_map
		)
		if not newly_short_loans and not newly_short_customers:
			return

		message = _(
			"Lowering the Loan To Value Ratio from {0}% to {1}% creates these shortfalls at the next "
			"shortfall check:"
		).format(old_ltv, flt(self.loan_to_value_ratio))
		if newly_short_loans:
			message += "<br>" + _("Loans: {0}").format(
				", ".join(frappe.bold(loan) for loan in newly_short_loans)
			)
		if newly_short_customers:
			message += "<br>" + _("Customers: {0}").format(
				", ".join(frappe.bold(customer) for customer in newly_short_customers)
			)

		frappe.msgprint(message, title=_("Running Loans Affected"), indicator="orange")

	def get_assignments_with_this_security(self):
		pledge = frappe.qb.DocType("Pledge")
		assignment = frappe.qb.DocType("Loan Security Assignment")

		return (
			frappe.qb.from_(pledge)
			.inner_join(assignment)
			.on(pledge.parent == assignment.name)
			.select(assignment.loan, assignment.applicant_type, assignment.applicant)
			.distinct()
			.where(pledge.loan_security == self.name)
			.where(assignment.docstatus == 1)
			.where(assignment.status == "Pledged")
			.run(as_dict=True)
		)

	def get_pledges_by_running_loan(self, loan_names):
		from lending.loan_management.doctype.loan_security_release.loan_security_release import (
			get_pledged_security_qty,
		)
		from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
			LOAN_OUTSTANDING_FIELDS,
		)

		if not loan_names:
			return []

		# get_list, not get_all: the user only sees loans they may read
		loans = frappe.get_list(
			"Loan",
			fields=LOAN_OUTSTANDING_FIELDS,
			filters={
				"name": ("in", list(loan_names)),
				"status": ("in", ["Disbursed", "Partially Disbursed"]),
				"is_secured_loan": 1,
			},
			limit=0,
		)
		return [(loan, get_pledged_security_qty(loan=loan.name)) for loan in loans]

	def get_pledges_by_customer(self, customers):
		from lending.loan_management.doctype.loan_security_release.loan_security_release import (
			get_pledged_security_qty,
		)

		if not customers or not frappe.has_permission("Customer", "read"):
			return {}

		visible_customers = frappe.get_list(
			"Customer", filters={"name": ("in", list(customers))}, pluck="name", limit=0
		)
		return {
			customer: get_pledged_security_qty(applicant=customer) for customer in visible_customers
		}


def get_newly_short_loans(pledges_by_loan, price_map, old_ltv_map, new_ltv_map):
	from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
		get_loan_shortfall,
	)

	def is_short(loan, pledges, ltv_map):
		_outstanding, security_value, shortfall_amount = get_loan_shortfall(
			loan, pledges, price_map, ltv_map
		)
		return security_value and flt(shortfall_amount, 6) > 0

	return [
		loan.name
		for loan, pledges in pledges_by_loan
		if is_short(loan, pledges, new_ltv_map) and not is_short(loan, pledges, old_ltv_map)
	]


def get_newly_short_customers(pledges_by_customer, price_map, old_ltv_map, new_ltv_map):
	from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
		get_allowed_amount,
		get_pending_principal_amount_for_applicant,
	)

	newly_short = []
	for customer, pledges in pledges_by_customer.items():
		pending_principal = get_pending_principal_amount_for_applicant(customer)
		_value, old_allowed = get_allowed_amount(pledges, price_map, old_ltv_map)
		_value, new_allowed = get_allowed_amount(pledges, price_map, new_ltv_map)

		if flt(new_allowed) < pending_principal <= flt(old_allowed):
			newly_short.append(customer)

	return newly_short


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
