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
	set_ltv_from_haircut,
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
		ltv_before_upgrade: DF.Percent
		original_security_value: DF.Currency
		override_haircut: DF.Check
		utilized_security_value: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.set_haircut()
		self.update_available_security_value()

	def set_haircut(self):
		type_haircut = flt(frappe.db.get_value("Loan Security Type", self.loan_security_type, "haircut"))

		if self.override_haircut:
			self.ltv_before_upgrade = None
		else:
			self.haircut = type_haircut

		set_ltv_from_haircut(self)

		if self.override_haircut and flt(self.haircut) < type_haircut and self.haircut_or_override_changed():
			frappe.msgprint(
				_("{0} now lends {1}%, more than its type {2} ({3}%).").format(
					frappe.bold(self.loan_security_name),
					flt(self.loan_to_value_ratio),
					frappe.bold(self.loan_security_type),
					100 - type_haircut,
				),
				indicator="orange",
			)

	def haircut_or_override_changed(self):
		return self.is_new() or self.has_value_changed("haircut") or self.has_value_changed("override_haircut")

	def update_available_security_value(self):
		self.available_security_value = flt(self.original_security_value) - flt(
			self.utilized_security_value
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
