# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class LoanSecurityPrice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		loan_security: DF.Link
		loan_security_name: DF.Data | None
		loan_security_price: DF.Currency
		loan_security_type: DF.Link | None
		valid_from: DF.Datetime
		valid_upto: DF.Datetime
	# end: auto-generated types

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

	return loan_security_price
