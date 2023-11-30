# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)


class LoanSecurity(Document):
	def before_insert(self):
		self.available_security_value = self.original_security_value


@frappe.whitelist()
def get_loan_security_price_or_value(loan_security):
	loan_security_price = get_loan_security_price(loan_security)

	if loan_security_price:
		return {"qty": None, "value": loan_security_price}

	return {
		"qty": 1,
		"value": frappe.db.get_value("Loan Security", loan_security, "available_security_value"),
	}
