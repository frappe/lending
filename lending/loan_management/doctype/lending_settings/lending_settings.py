# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class LendingSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		auto_create_customer: DF.Check
		enable_margin_call: DF.Check
		margin_cure_days: DF.Int
		portal_logo: DF.AttachImage | None
		sale_charge: DF.Link | None
	# end: auto-generated types

	def validate(self):
		# Sites from before this field read it as 0, which would escalate a margin call on the day after its notice
		if self.enable_margin_call and cint(self.margin_cure_days) < 1:
			frappe.throw(
				_("Set Margin Cure Days to at least 1 before you enable margin calls"),
				title=_("Margin Cure Days Missing"),
			)
