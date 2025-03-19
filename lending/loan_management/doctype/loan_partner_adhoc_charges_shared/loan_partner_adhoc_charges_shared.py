# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanPartnerAdhocChargesShared(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		charge_type: DF.Link | None
		own_ratio: DF.Percent
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		partner_percentage: DF.Percent
		partner_ratio: DF.Percent
		sharing_parameter: DF.Literal["", "Ratio", "Percentage"]
	# end: auto-generated types

	pass
