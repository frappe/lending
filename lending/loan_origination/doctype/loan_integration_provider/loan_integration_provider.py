# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LoanIntegrationProvider(Document):
	"""Which outside service answers for a kind of work, and which adapter speaks to it.

	Deliberately holds no URL and no credential. Those belong to whichever app owns the
	vendor — Surepass to ekyc_india, the way Digio already is — because a vendor is usually
	specific to one country while lending is not. Two possible homes for a token is how
	somebody fills in the wrong one and spends an afternoon on a 401.
	"""

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
		# Imported here rather than at module level: the registry imports the adapters, and the
		# adapters import this app, so a top level import closes the loop.
		from lending.loan_integrations.adapters import adapter_choices

		choices = adapter_choices(self.provider_type)

		if self.adapter in choices:
			return

		# The adapter dropdown is filled in by the client script, which only the browser obeys.
		# A REST caller can send anything, so the check has to happen here too.
		frappe.throw(
			_("{0} is not a registered adapter for provider type {1}. Registered adapters: {2}.").format(
				self.adapter, self.provider_type, ", ".join(choices) or _("none")
			)
		)

	def set_settings_doctype(self):
		"""Record which form holds this provider's credentials, so nobody has to hunt for it."""
		from lending.loan_integrations.adapters import get_adapter_class

		self.settings_doctype = get_adapter_class(self.adapter).settings_doctype or None
