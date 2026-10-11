# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class LoanSecurityType(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		disabled: DF.Check
		haircut: DF.Percent
		loan_security_type: DF.Data
		loan_to_value_ratio: DF.Percent
	# end: auto-generated types

	def validate(self):
		set_ltv_from_haircut(self)

	def on_update(self):
		if self.has_value_changed("haircut"):
			self.update_securities_following_type()

	def update_securities_following_type(self):
		loan_security = frappe.qb.DocType("Loan Security")
		(
			frappe.qb.update(loan_security)
			.set(loan_security.haircut, self.haircut)
			.set(loan_security.loan_to_value_ratio, self.loan_to_value_ratio)
			.where(loan_security.loan_security_type == self.name)
			.where(loan_security.override_haircut == 0)
		).run()


def set_ltv_from_haircut(doc):
	# Drawing power reads the haircut and the shortfall checks read the LTV,
	# so only the haircut is an input and the LTV always follows it.
	if not 0 <= flt(doc.haircut) <= 100:
		frappe.throw(_("{0} must be between 0 and 100.").format(frappe.bold(doc.meta.get_label("haircut"))))

	doc.loan_to_value_ratio = 100 - flt(doc.haircut)
