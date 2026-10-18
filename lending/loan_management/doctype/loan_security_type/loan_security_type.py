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
		is_mutual_fund: DF.Check
		loan_security_type: DF.Data
		loan_to_value_ratio: DF.Percent
		price_validity_days: DF.Int
		sell_ltv: DF.Percent
	# end: auto-generated types

	def validate(self):
		validate_sell_ltv(self)


def validate_sell_ltv(doc):
	if flt(doc.sell_ltv) and flt(doc.sell_ltv) < flt(doc.loan_to_value_ratio):
		frappe.throw(
			_("Sell LTV {0}% cannot be lower than the Loan To Value Ratio {1}%").format(
				flt(doc.sell_ltv), flt(doc.loan_to_value_ratio)
			)
		)
