# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class LoanIntegrationProvider(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		adapter: DF.Literal[None]
		api_client_id: DF.Password | None
		api_secret: DF.Password | None
		enable_production: DF.Check
		enable_sandbox: DF.Check
		extra_config: DF.SmallText | None
		is_active: DF.Check
		member_id: DF.Data | None
		production_url: DF.Data | None
		provider_name: DF.Data
		provider_type: DF.Literal["Credit Bureau", "KYC", "Payment-Mandate", "Account Aggregator"]
		sandbox_api_client_id: DF.Password | None
		sandbox_api_secret: DF.Password | None
		sandbox_url: DF.Data | None
		timeout: DF.Int
	# end: auto-generated types

	def validate(self):
		self.normalise_urls()
		self.validate_environment()
		self.validate_extra_config()
		self.validate_adapter()

	def normalise_urls(self):
		for fieldname in ("production_url", "sandbox_url"):
			if url := self.get(fieldname):
				self.set(fieldname, url.strip().rstrip("/"))

	def validate_environment(self):
		if not self.enable_production and not self.enable_sandbox:
			frappe.throw(
				_(
					"Enable either Sandbox or Production for {0}, otherwise there is no address to call."
				).format(self.name or self.provider_name)
			)

	def validate_extra_config(self):
		if not self.extra_config:
			return

		try:
			config = json.loads(self.extra_config)
		except json.JSONDecodeError as e:
			frappe.throw(_("Extra Config is not valid JSON: {0}").format(e))

		if not isinstance(config, dict):
			frappe.throw(_("Extra Config has to be a JSON object, such as {0}.").format('{"key": "value"}'))

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
