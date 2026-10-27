# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class PromisetoPay(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		actual_paid_amount: DF.Currency
		captured_by: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		promised_amount: DF.Currency
		promised_date: DF.Date
		remarks: DF.SmallText | None
		status: DF.Literal["Open", "Kept", "Broken", "Partial"]
	# end: auto-generated types

	pass
