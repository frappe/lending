# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)


class LoanSecurityPledge(Document):
	def validate(self):
		self.set_missing_values()
		self.set_pledge_amount()
		self.validate_duplicate_securities_and_collaterals()
		self.validate_loan_collaterals()
		self.validate_loan_security_type()

	def set_missing_values(self):
		if not self.collateral_type:
			if self.loan:
				self.collateral_type = frappe.db.get_value("Loan", self.loan, "collateral_type")
			elif self.loan_application:
				self.collateral_type = frappe.db.get_value("Loan", self.loan_application, "collateral_type")

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

	def validate_loan_collaterals(self):
		for collateral in self.collaterals:
			status, loan_applicant = frappe.db.get_value(
				"Loan Collateral", collateral, ["status", "loan_applicant"]
			)
			if status in ["Released", "Repossessed"]:
				frappe.throw(
					_("Row {0}: released or repossessed collateral cannot be hypothecated").format(collateral.idx)
				)
			if loan_applicant != self.applicant:
				frappe.throw(
					_("Row {0}: collateral applicant does not match loan applicant").format(collateral.idx)
				)

	def validate_duplicate_securities_and_collaterals(self):
		security_list = []
		for security in self.securities:
			if security.loan_security not in security_list:
				security_list.append(security.loan_security)
			else:
				frappe.throw(
					_("Loan Security {0} added multiple times").format(frappe.bold(security.loan_security))
				)

		collateral_list = []
		for collateral in self.collaterals:
			if collateral.loan_collateral not in collateral_list:
				collateral_list.append(collateral.loan_collateral)
			else:
				frappe.throw(
					_("Loan Collateral {0} added multiple times").format(frappe.bold(collateral.loan_collateral))
				)

	def validate_loan_security_type(self):
		if not self.collateral_type == "Loan Security":
			return

		existing_pledge = ""

		if self.loan:
			existing_pledge = frappe.db.get_value(
				"Loan Security Pledge", {"loan": self.loan, "docstatus": 1}, ["name"]
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

		if self.collateral_type == "Loan Security":
			for pledge in self.securities:
				if not pledge.qty and not pledge.amount:
					frappe.throw(_("Qty or Amount is mandatory for loan security!"))

				if not (self.loan_application and pledge.loan_security_price):
					pledge.loan_security_price = get_loan_security_price(pledge.loan_security)

				if not pledge.qty:
					pledge.qty = cint(pledge.amount / pledge.loan_security_price)

				pledge.amount = pledge.qty * pledge.loan_security_price
				pledge.post_haircut_amount = cint(pledge.amount - (pledge.amount * pledge.haircut / 100))

				total_security_value += pledge.amount
				maximum_loan_value += pledge.post_haircut_amount
		else:
			for collateral in self.collaterals:
				total_security_value += collateral.available_collateral_value
			maximum_loan_value = total_security_value

		self.total_security_value = total_security_value
		self.maximum_loan_value = maximum_loan_value


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
