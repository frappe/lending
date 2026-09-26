# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

# Keyed by site: one worker serves every site, and the adapters are whatever apps that one
# site installed. Registered by path, not by import, since Python imports a module once.
_REGISTRIES: dict[str | None, dict[str, type]] = {}
_LOADED: set[str | None] = set()

_BUILTIN_ADAPTERS = ()


def _site():
	return getattr(frappe.local, "site", None)


def registry() -> dict[str, type]:
	return _REGISTRIES.setdefault(_site(), {})


def register(cls):
	registry()[cls.key] = cls

	return cls


def _load():
	site = _site()

	if site in _LOADED:
		return

	for path in (*_BUILTIN_ADAPTERS, *frappe.get_hooks("lending_integration_adapters")):
		register(frappe.get_attr(path))

	_LOADED.add(site)


def get_adapter_class(adapter: str) -> type:
	_load()

	cls = registry().get(adapter)

	if not cls:
		frappe.throw(
			_("No adapter is registered for {0}. Registered adapters: {1}.").format(
				adapter, ", ".join(sorted(registry())) or _("none")
			)
		)

	return cls


def get_adapter(adapter: str):
	return get_adapter_class(adapter)()


def adapter_keys(provider_type: str | None = None) -> list[str]:
	_load()

	return sorted(
		key
		for key, cls in registry().items()
		if not provider_type or cls.provider_type == provider_type
	)


@frappe.whitelist(methods=["GET"])
def adapter_choices(provider_type: str | None = None) -> list[str]:
	# Read, not write: the form calls this on refresh to render the saved value too.
	frappe.has_permission("Loan Origination Settings", "read", throw=True)

	return adapter_keys(provider_type)
