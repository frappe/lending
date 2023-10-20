# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	get_pending_principal_amount,
)

# from lending.loan_management.doctype.loan_security_price.loan_security_price import (
# 	get_loan_security_price,
# )
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)


class LoanSecurityAssignment(Document):
	def validate(self):
		self.set_pledge_amount()
		self.set_loan_and_pending_amounts()
		self.validate_duplicate_securities()
		self.validate_loan_security_type()

	def on_submit(self):
		if self.loan:
			self.db_set("status", "Pledged")
			self.db_set("pledge_time", now_datetime())
			update_shortfall_status(self.loan, self.total_security_value)
			update_loan(self.loan, self.maximum_loan_value)

	def on_cancel(self):
		if self.loan:
			self.db_set("status", "Cancelled")
			self.db_set("pledge_time", None)
			update_loan(self.loan, self.maximum_loan_value, cancel=1)

	def validate_duplicate_securities(self):
		security_list = []
		for security in self.securities:
			if security.loan_security not in security_list:
				security_list.append(security.loan_security)
			else:
				frappe.throw(
					_("Loan Security {0} added multiple times").format(frappe.bold(security.loan_security))
				)

	def validate_loan_security_type(self):
		existing_pledge = ""

		for d in self.get("allocated_loans"):
			if d.loan:
				existing_pledge = frappe.db.get_value(
					"Loan Security Assignment", {"loan": d.loan, "docstatus": 1}, ["name"]
				)

		if existing_pledge:
			loan_security_type = frappe.db.get_value(
				"Pledge", {"parent": existing_pledge}, ["loan_security_type"]
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

	def set_pledge_amount(self):
		total_security_value = 0
		maximum_loan_value = 0

		for pledge in self.securities:
			if not pledge.qty and not pledge.amount:
				frappe.throw(_("Qty or Amount is mandatory for loan security!"))

			if not pledge.qty and pledge.loan_security_price:
				pledge.qty = cint(pledge.amount / pledge.loan_security_price)
			elif not pledge.loan_security_price:
				pledge.qty = 1

			if pledge.loan_security_price:
				pledge.amount = pledge.qty * pledge.loan_security_price
			else:
				pledge.loan_security_price = flt(pledge.amount / pledge.qty)

			pledge.post_haircut_amount = cint(pledge.amount - (pledge.amount * pledge.haircut / 100))

			total_security_value += pledge.amount
			maximum_loan_value += pledge.post_haircut_amount

		self.total_security_value = total_security_value
		self.maximum_loan_value = maximum_loan_value

	def set_loan_and_pending_amounts(self):
		total_pending_principal = 0
		total_loan_amount = 0
		for loan in self.get("allocated_loans"):
			loan.pending_principal_amount = get_pending_principal_amount(frappe.get_doc("Loan", loan.loan))
			total_pending_principal += loan.pending_principal_amount
			total_loan_amount += loan.loan_amount

		self.total_loan_amount = total_loan_amount
		self.total_pending_principal = total_pending_principal
		self.utilized_security_value = min(self.total_pending_principal, self.total_security_value)
		self.pending_security_value = self.total_security_value - self.utilized_security_value


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
