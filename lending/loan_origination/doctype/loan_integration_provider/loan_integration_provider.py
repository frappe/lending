# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LoanIntegrationProvider(Document):
	"""Holds no URL and no credential: those belong to the app that owns the vendor."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		adapter: DF.Literal[None]
		is_active: DF.Check
		provider_name: DF.Data
		provider_type: DF.Literal["Credit Bureau", "KYC", "Payment-Mandate", "Account Aggregator"]
		settings_doctype: DF.Link | None
	# end: auto-generated types

	def validate(self):
		self.validate_adapter()
		self.set_settings_doctype()

	def validate_adapter(self):
		# Imported here: a module level import closes a loop through the registry.
		from lending.loan_integrations.adapters import adapter_keys

		choices = adapter_keys(self.provider_type)

		if self.adapter in choices:
			return

		frappe.throw(
			_("{0} is not a registered adapter for provider type {1}. Registered adapters: {2}.").format(
				self.adapter, self.provider_type, ", ".join(choices) or _("none")
			)
		)

	def set_settings_doctype(self):
		from lending.loan_integrations.adapters import get_adapter_class

		self.settings_doctype = get_adapter_class(self.adapter).settings_doctype or None
