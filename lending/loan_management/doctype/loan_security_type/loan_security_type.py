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
		validate_haircut_and_ltv(self)


def validate_haircut_and_ltv(doc):
	if not 0 <= flt(doc.haircut) <= 100:
		frappe.throw(_("Haircut must be between 0 and 100."))

	if not 0 < flt(doc.loan_to_value_ratio) <= 100:
		frappe.throw(_("Loan To Value Ratio must be more than 0 and at most 100."))

	warn_if_loans_start_in_shortfall(doc)


def warn_if_loans_start_in_shortfall(doc):
	if flt(doc.haircut) + flt(doc.loan_to_value_ratio) >= 100:
		return

	frappe.msgprint(
		_(
			"Haircut {0}% lends up to {1}% of the security value, but the Loan To Value Ratio of {2}% "
			"raises a shortfall above {2}%. Loans will start in shortfall. "
			"Keep Haircut + Loan To Value Ratio at 100 or more."
		).format(flt(doc.haircut), 100 - flt(doc.haircut), flt(doc.loan_to_value_ratio)),
		title=_("Haircut and Loan To Value Ratio Mismatch"),
		indicator="orange",
	)
