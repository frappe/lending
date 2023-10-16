# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime


class LoanSecurityPrice(Document):
	def validate(self):
		self.validate_dates()

	def validate_dates(self):

		if self.valid_from > self.valid_upto:
			frappe.throw(_("Valid From Time must be lesser than Valid Upto Time."))

		existing_loan_security = frappe.db.sql(
			""" SELECT name from `tabLoan Security Price`
			WHERE loan_security = %s AND name != %s AND (valid_from BETWEEN %s and %s OR valid_upto BETWEEN %s and %s) """,
			(
				self.loan_security,
				self.name,
				self.valid_from,
				self.valid_upto,
				self.valid_from,
				self.valid_upto,
			),
		)

		if existing_loan_security:
			frappe.throw(_("Loan Security Price overlapping with {0}").format(existing_loan_security[0][0]))

	def after_insert(self):
		self.set_initial_loan_security_details()

	def set_initial_loan_security_details(self):
		if frappe.db.count("Loan Security Price", {"loan_security": self.loan_security}) > 1:
			return

		loan_security = frappe.db.get_value(
			"Loan Security", self.loan_security, ["haircut", "qty"], as_dict=True
		)

		security_price = self.loan_security_price
		security_value = loan_security.qty * security_price
		post_haircut_value = flt(security_value - (security_value * loan_security.haircut / 100))

		frappe.db.set_value(
			"Loan Security",
			self.loan_security,
			{
				"original_security_price": security_price,
				"original_security_value": security_value,
				"original_post_haircut_value": post_haircut_value,
			},
		)


@frappe.whitelist()
def get_loan_security_price(loan_security, valid_time=None):
	if not valid_time:
		valid_time = get_datetime()

	loan_security_price = frappe.db.get_value(
		"Loan Security Price",
		{
			"loan_security": loan_security,
			"valid_from": ("<=", valid_time),
			"valid_upto": (">=", valid_time),
		},
		"loan_security_price",
	)

	if not loan_security_price:
		frappe.throw(_("No valid Loan Security Price found for {0}").format(frappe.bold(loan_security)))
	else:
		return loan_security_price
