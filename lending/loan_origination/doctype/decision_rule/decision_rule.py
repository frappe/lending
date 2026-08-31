# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class DecisionRule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		operator: DF.Literal["", ">", ">=", "<", "<=", "==", "!=", "in", "not in", "between"]
		outcome: DF.Literal["", "Approve", "Decline", "Refer"]
		reason_code: DF.Link | None
		sequence: DF.Int
		stop_on_match: DF.Check
		term_amount_cap: DF.Currency
		term_roi_override: DF.Percent
		term_tenure_cap: DF.Int
		value: DF.Data
		variable: DF.Autocomplete
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	pass
