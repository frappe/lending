# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.utils import flt

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
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
		original_security_value: DF.Currency
		utilized_security_value: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.update_available_security_value()

	def update_available_security_value(self):
		self.available_security_value = flt(self.original_security_value) - flt(
			self.utilized_security_value
		)


@frappe.whitelist()
def get_loan_security_price_or_value(loan_security):
	loan_security_price = get_loan_security_price(loan_security)

	if loan_security_price:
		return {"qty": None, "value": loan_security_price}

	return {
		"qty": 1,
		"value": frappe.db.get_value("Loan Security", loan_security, "available_security_value"),
	}
