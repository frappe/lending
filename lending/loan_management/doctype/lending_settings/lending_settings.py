# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint

from lending.portal.brand import brand_style, swatch
from lending.portal.presets import CUSTOM, PRESETS, resolve

APPLY_ROUTE = "/apply"


class LendingSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from frappe.website.doctype.top_bar_item.top_bar_item import TopBarItem

		auto_create_customer: DF.Check
		enable_borrower_portal: DF.Check
		enable_public_apply: DF.Check
		portal_appearance: DF.Literal["System", "Light", "Dark"]
		portal_brand_name: DF.Data | None
		portal_copyright: DF.Data | None
		portal_footer_links: DF.Table[TopBarItem]
		portal_logo: DF.AttachImage | None
		portal_primary_color: DF.Color | None
		portal_secondary_color: DF.Color | None
		portal_support_email: DF.Data | None
		portal_theme: DF.Literal[
			"",
			"Ocean",
			"Navy & Teal",
			"Forest",
			"Teal & Orange",
			"Royal",
			"Plum",
			"Indigo",
			"Graphite",
			"Custom",
		]
	# end: auto-generated types

	def on_update(self):
		sync_portal_pages()


@frappe.whitelist()
def get_theme_swatches(primary_color: str | None = None, secondary_color: str | None = None) -> dict:
	"""Every preset, then Custom from the colours on the form, painted as the portal will paint them."""
	frappe.has_permission("Lending Settings", "write", throw=True)

	swatches = {name: swatch(*preset) for name, preset in PRESETS.items()}
	swatches[CUSTOM] = swatch(primary_color, secondary_color)

	return swatches


@frappe.whitelist()
def get_theme_preview(
	theme: str | None = None, primary_color: str | None = None, secondary_color: str | None = None
) -> str:
	"""The portal stylesheet for the form's unsaved theme, for Desk's live preview."""
	frappe.has_permission("Lending Settings", "write", throw=True)

	return brand_style(*resolve(theme, primary_color, secondary_color))


def sync_portal_pages():
	portal_on = cint(frappe.db.get_single_value("Lending Settings", "enable_borrower_portal"))
	apply_on = portal_on and cint(
		frappe.db.get_single_value("Lending Settings", "enable_public_apply")
	)

	pages = frappe.get_all(
		"Studio Page",
		filters={"studio_app": portal_app()},
		fields=["name", "route", "published"],
	)

	changed = False
	for page in pages:
		wanted = apply_on if page.route == APPLY_ROUTE else portal_on
		if cint(page.published) == cint(wanted):
			continue

		# A save would export the page back over lending/studio/ in developer mode.
		frappe.db.set_value("Studio Page", page.name, "published", cint(wanted))
		frappe.clear_document_cache("Studio Page", page.name)
		changed = True

	if changed:
		frappe.clear_cache()


def portal_app() -> str:
	from lending.portal.studio_build.app import APP_NAME

	return APP_NAME
