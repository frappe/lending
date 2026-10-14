# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class DunningRule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		cadence_days: DF.Int
		classification_code: DF.Link | None
		company: DF.Link
		disabled: DF.Check
		loan_product: DF.Link | None
		max_dpd: DF.Int
		min_dpd: DF.Int
		rule_name: DF.Data
	# end: auto-generated types

	def validate(self):
		if self.min_dpd > self.max_dpd:
			frappe.throw(_("Min DPD cannot be greater than Max DPD"))
