# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class CollectionActivity(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		activity_date: DF.Datetime
		activity_type: DF.Literal[
			"Call", "SMS", "Email", "WhatsApp", "Field Visit", "Legal Notice", "System Dunning"
		]
		agent: DF.Link | None
		channel: DF.Literal["", "Email", "SMS", "WhatsApp", "Phone", "In Person"]
		notes: DF.SmallText | None
		outcome: DF.Literal[
			"", "Answered", "No Response", "Promise to Pay", "Dispute Raised", "Paid", "Refused", "Number Unreachable"
		]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		template_used: DF.Link | None
	# end: auto-generated types

	pass
