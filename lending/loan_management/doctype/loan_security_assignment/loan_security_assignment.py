# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)


class LoanSecurityAssignment(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.pledge.pledge import Pledge

		amended_from: DF.Link | None
		applicant: DF.DynamicLink
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		company: DF.Link
		description: DF.Text | None
		loan: DF.Link | None
		loan_application: DF.Link | None
		maximum_loan_value: DF.Currency
		pledge_time: DF.Datetime | None
		reference_no: DF.Data | None
		release_time: DF.Datetime | None
		securities: DF.Table[Pledge]
		status: DF.Literal[
			"Pledge Requested",
			"Unpledged",
			"Pledged",
			"Release Requested",
			"Released",
			"Repossessed",
			"Cancelled",
		]
		total_security_value: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.validate_securities()
		self.validate_loan_security_type()
		self.set_loan_and_security_values()

	def on_submit(self):
		if self.loan:
			self.db_set("status", "Pledged")
			self.db_set("pledge_time", now_datetime())
			update_shortfall_status(self.loan, self.total_security_value)
			update_loan(self.loan, self.maximum_loan_value)

	def on_update_after_submit(self):
		self.check_loan_securities_capability_to_book_additional_loans()

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		self.db_set("pledge_time", None)
		update_loan(self.loan, self.maximum_loan_value, cancel=1)

	def validate_securities(self):
		security_list = []
		for security in self.securities:
			if security.loan_security not in security_list:
				security_list.append(security.loan_security)
			else:
				frappe.throw(
					_("Loan Security {0} added multiple times").format(frappe.bold(security.loan_security))
				)

	def validate_loan_security_type(self):
		existing_lsa = frappe.db.get_value(
			"Loan Security Assignment", {"loan": self.loan, "docstatus": 1}, ["name"]
		)

		if existing_lsa:
			loan_security_type = frappe.db.get_value(
				"Pledge", {"parent": existing_lsa}, ["loan_security_type"]
			)
		else:
			loan_security_type = self.securities[0].loan_security_type

		ltv_ratio_map = frappe._dict(
			frappe.get_all("Loan Security Type", fields=["name", "loan_to_value_ratio"], as_list=1)
		)

		ltv_ratio = ltv_ratio_map.get(loan_security_type)

		for security in self.securities:
			if ltv_ratio_map.get(security.loan_security_type) != ltv_ratio:
				frappe.throw(_("Loan Securities with different LTV ratio cannot be pledged against one loan"))

	def set_loan_and_security_values(self):
		total_security_value = 0
		maximum_loan_value = 0

		for pledge in self.securities:
			if not pledge.qty:
				frappe.throw(_("Qty is mandatory for loan security!"))

			if not pledge.loan_security_price:
				loan_security_price = get_loan_security_price(pledge.loan_security)

				if loan_security_price:
					pledge.loan_security_price = loan_security_price
				else:
					frappe.throw(
						_("No valid Loan Security Price found for {0}").format(frappe.bold(pledge.loan_security))
					)

			pledge.amount = pledge.qty * pledge.loan_security_price
			pledge.post_haircut_amount = cint(pledge.amount - (pledge.amount * pledge.haircut / 100))

			total_security_value += pledge.amount
			maximum_loan_value += pledge.post_haircut_amount

		self.total_security_value = total_security_value
		self.maximum_loan_value = maximum_loan_value

	def check_loan_securities_capability_to_book_additional_loans(self):
		loan_amount, status = frappe.db.get_value("Loan", self.loan, ["loan_amount", "status"])

		if status != "Sanctioned":
			return

		total_security_value_needed = loan_amount

		total_available_security_value = 0
		for d in self.get("securities"):
			total_available_security_value += frappe.db.get_value(
				"Loan Security", d.loan_security, "available_security_value"
			)

		if total_security_value_needed > total_available_security_value:
			frappe.throw(
				_("Loan Securities worth {0} needed more to book the loan").format(
					frappe.bold(flt(total_security_value_needed - total_available_security_value, 2)),
				)
			)

		update_loan(self.loan, total_available_security_value)


def update_loan(loan, maximum_value_against_pledge, cancel=0):
	maximum_loan_value = frappe.db.get_value("Loan", {"name": loan}, ["maximum_loan_amount"])

	if cancel:
		frappe.db.sql(
			""" UPDATE `tabLoan` SET maximum_loan_amount=%s
			WHERE name=%s""",
			(maximum_loan_value - maximum_value_against_pledge, loan),
		)
	else:
		frappe.db.sql(
			""" UPDATE `tabLoan` SET maximum_loan_amount=%s, is_secured_loan=1
			WHERE name=%s""",
			(maximum_loan_value + maximum_value_against_pledge, loan),
		)


def update_loan_securities_values(
	loan,
	amount,
	trigger_doctype,
	on_trigger_doc_cancel=0,
):
	if not frappe.db.get_value("Loan", loan, "is_secured_loan"):
		return

	utilized_value_increased = (
		True
		if (trigger_doctype == "Loan Disbursement" and not on_trigger_doc_cancel)
		or (trigger_doctype == "Loan Repayment" and on_trigger_doc_cancel)
		else False
	)

	ls = frappe.qb.DocType("Loan Security")
	lsa = frappe.qb.DocType("Loan Security Assignment")
	pledge = frappe.qb.DocType("Pledge")

	loan_securities = (
		frappe.qb.from_(lsa)
		.inner_join(pledge)
		.on(pledge.parent == lsa.name)
		.inner_join(ls)
		.on(pledge.loan_security == ls.name)
		.select(
			ls.name,
			ls.available_security_value,
			ls.utilized_security_value,
			ls.original_security_value,
		)
		.where(lsa.status == "Pledged")
		.where(lsa.loan == loan)
	).run(as_dict=True)

	for loan_security in loan_securities:
		if amount <= 0:
			break

		if utilized_value_increased:
			if loan_security.utilized_security_value + amount > loan_security.original_security_value:
				new_utilized_security_value = loan_security.original_security_value
				new_available_security_value = 0
				amount = amount + loan_security.utilized_security_value - loan_security.original_security_value
			else:
				new_utilized_security_value = loan_security.utilized_security_value + amount
				new_available_security_value = loan_security.available_security_value - amount
				amount = 0
		else:
			if loan_security.available_security_value + amount > loan_security.original_security_value:
				new_available_security_value = loan_security.original_security_value
				new_utilized_security_value = 0
				amount = (
					amount + loan_security.available_security_value - loan_security.original_security_value
				)
			else:
				new_utilized_security_value = loan_security.utilized_security_value - amount
				new_available_security_value = loan_security.available_security_value + amount
				amount = 0

		frappe.db.set_value(
			"Loan Security",
			loan_security.name,
			{
				"utilized_security_value": new_utilized_security_value,
				"available_security_value": new_available_security_value,
			},
		)


@frappe.whitelist()
def release_loan_security_assignment(loan_security_assignment):
	frappe.db.set_value(
		"Loan Security Assignment",
		loan_security_assignment,
		{"status": "Released", "release_time": now_datetime()},
	)
