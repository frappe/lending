# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanChargeReference(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allocated_amount: DF.Currency
		charge: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pending_charge_amount: DF.Currency
		sales_invoice: DF.Link | None
	# end: auto-generated types

	pass
