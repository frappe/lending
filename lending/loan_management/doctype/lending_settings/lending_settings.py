# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LendingSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		auto_create_customer: DF.Check
		enable_margin_call: DF.Check
		margin_cure_days: DF.Int
		mutual_fund_nav_adapter: DF.Literal[None]
		mutual_fund_registry_adapter: DF.Literal[None]
		portal_logo: DF.AttachImage | None
		sale_charge: DF.Link | None
	# end: auto-generated types

	pass
