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
		sync_haircut_and_ltv(self)


def sync_haircut_and_ltv(doc, derive_haircut=True):
	# Drawing power reads the haircut and the shortfall check reads the LTV,
	# so the two must always describe the same split of the security value.
	# Pass derive_haircut=False where the haircut is fetched from elsewhere,
	# so that an LTV override is checked against it rather than rewriting it.
	validate_percent_range(doc, "haircut")
	validate_percent_range(doc, "loan_to_value_ratio")

	haircut = flt(doc.haircut)
	ltv = flt(doc.loan_to_value_ratio)

	if not haircut and not ltv:
		frappe.throw(
			_("Set {0} or {1}. A zero haircut needs a loan to value ratio of 100.").format(
				frappe.bold(doc.meta.get_label("haircut")),
				frappe.bold(doc.meta.get_label("loan_to_value_ratio")),
			),
			title=_("Haircut and LTV Missing"),
		)

	if not ltv:
		doc.loan_to_value_ratio = 100 - haircut
	elif not haircut and derive_haircut:
		doc.haircut = 100 - ltv
	elif flt(haircut + ltv, 6) != 100:
		frappe.throw(
			_("{0} and {1} must add up to 100. With a haircut of {2}%, the loan to value ratio is {3}%.").format(
				frappe.bold(doc.meta.get_label("haircut")),
				frappe.bold(doc.meta.get_label("loan_to_value_ratio")),
				haircut,
				100 - haircut,
			),
			title=_("Haircut and LTV Do Not Match"),
		)


def validate_percent_range(doc, fieldname):
	if not 0 <= flt(doc.get(fieldname)) <= 100:
		frappe.throw(_("{0} must be between 0 and 100.").format(frappe.bold(doc.meta.get_label(fieldname))))
