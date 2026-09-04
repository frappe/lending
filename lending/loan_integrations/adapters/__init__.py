# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

_REGISTRY: dict[str, type] = {}
_LOADED = False

# Adapters shipped with this app. Other apps add their own through the
# lending_integration_adapters hook, without touching this list.
_BUILTIN_ADAPTERS = ()


def register(cls):
	"""Class decorator that puts an adapter in the registry under its key."""
	_REGISTRY[cls.key] = cls

	return cls


def _load():
	global _LOADED

	# A plain `if not _REGISTRY` would be wrong: an adapter that raises halfway through import
	# leaves the registry non-empty but incomplete, and the truthiness check would then lock
	# that partial registry in for the life of the process.
	if _LOADED:
		return

	for name in _BUILTIN_ADAPTERS:
		frappe.get_module(f"lending.loan_integrations.adapters.{name}")

	for path in frappe.get_hooks("lending_integration_adapters"):
		register(frappe.get_attr(path))

	_LOADED = True


def get_adapter(provider_name: str):
	_load()

	provider = frappe.get_cached_doc("Loan Integration Provider", provider_name)

	if not provider.is_active:
		frappe.throw(_("Integration provider {0} is not active.").format(provider_name))

	cls = _REGISTRY.get(provider.adapter)

	if not cls:
		frappe.throw(
			_("No adapter is registered for {0}, so {1} cannot be called.").format(
				provider.adapter, provider_name
			)
		)

	return cls(provider)


@frappe.whitelist(methods=["GET"])
def adapter_choices(provider_type: str | None = None) -> list[str]:
	"""Registered adapter keys, narrowed to one provider type. Fills the adapter dropdown."""
	_load()

	return sorted(
		key
		for key, cls in _REGISTRY.items()
		if not provider_type or cls.provider_type == provider_type
	)
