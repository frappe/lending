# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


# import frappe
from frappe.model.document import Document


class GoldLTVSlab(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		ltv: DF.Percent
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		up_to_amount: DF.Currency
	# end: auto-generated types

	pass
