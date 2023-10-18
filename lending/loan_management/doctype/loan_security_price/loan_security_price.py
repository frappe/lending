# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime

from lending.loan_management.doctype.loan_security_utilized_and_available_value_log.loan_security_utilized_and_available_value_log import (
	create_loan_security_utilized_and_available_value_log,
)


class LoanSecurityPrice(Document):
	def validate(self):
		self.validate_dates()
		self.set_missing_values()

	def set_missing_values(self):
		if self.quantifiable:
			self.loan_security_value = flt(self.quantity * self.loan_security_price)
		else:
			self.quantity = 1
			self.loan_security_price = self.loan_security_value

		self.loan_post_haircut_security_value = flt(
			self.loan_security_value - (self.loan_security_value * self.haircut / 100)
		)

	def on_submit(self):
		self.update_loan_available_security_value()

	def on_cancel(self):
		self.update_loan_available_security_value(cancel=True)

	def validate_dates(self):
		if self.valid_from > self.valid_upto:
			frappe.throw(_("Valid From Time must be lesser than Valid Upto Time."))

		existing_loan_security = frappe.db.sql(
			""" SELECT name from `tabLoan Security Price`
			WHERE loan_security = %s AND name != %s AND docstatus = 1 AND (valid_from BETWEEN %s and %s OR valid_upto BETWEEN %s and %s) """,
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

	def update_loan_available_security_value(self, cancel=False):
		available_security_value, original_post_haircut_security_value = frappe.db.get_value(
			"Loan Security",
			self.loan_security,
			["available_security_value", "original_post_haircut_security_value"],
		)

		if not cancel:
			latest_post_haircut_security_value = frappe.db.get_list(
				"Loan Security Price",
				filters={"loan_security": self.loan_security, "docstatus": 1},
				fields=["loan_post_haircut_security_value"],
				order_by="creation desc",
				page_length=1,
				as_list=True,
			)

			if latest_post_haircut_security_value:
				latest_post_haircut_security_value = latest_post_haircut_security_value[0][0]
			else:
				latest_post_haircut_security_value = original_post_haircut_security_value

			new_available_security_value = flt(
				(available_security_value * latest_post_haircut_security_value)
				/ original_post_haircut_security_value
			)
		else:
			new_available_security_value = frappe.db.get_list(
				"Loan Security Utilized and Available Value Log",
				filters={"loan_security": self.loan_security, "trigger_document": self.name},
				fields=["previous_available_security_value"],
				order_by="creation desc",
				page_length=1,
				as_list=True,
			)[0][0]

		frappe.db.set_value(
			"Loan Security", self.loan_security, "available_security_value", new_available_security_value
		)

		create_loan_security_utilized_and_available_value_log(
			loan_security=self.loan_security,
			trigger_doctype="Loan Security Price",
			trigger_document=self.name,
			on_trigger_doc_cancel=cancel,
			new_available_security_value=new_available_security_value,
			new_utilized_security_value=None,
			previous_available_security_value=available_security_value,
			previous_utilized_security_value=None,
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
			"docstatus": 1,
		},
		"loan_security_price",
	)

	if loan_security_price:
		return loan_security_price
	else:
		return frappe.db.get_value("Loan Security", loan_security, "original_security_price")
