# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

APPLY_ROUTE = "/apply"
# Pages a visitor uses to become a borrower, published only with the public form.
PUBLIC_APPLY_ROUTES = (APPLY_ROUTE, "/register")


class LendingSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from frappe.website.doctype.top_bar_item.top_bar_item import TopBarItem

		from lending.loan_management.doctype.portal_secured_loan.portal_secured_loan import (
			PortalSecuredLoan,
		)

		auto_create_customer: DF.Check
		enable_borrower_portal: DF.Check
		enable_margin_call: DF.Check
		enable_public_apply: DF.Check
		margin_cure_days: DF.Int
		mutual_fund_nav_adapter: DF.Literal[None]
		mutual_fund_registry_adapter: DF.Literal[None]
		portal_brand_name: DF.Data | None
		portal_copyright: DF.Data | None
		portal_footer_links: DF.Table[TopBarItem]
		portal_loan_approval: DF.Literal["Automatic", "Staff Review"]
		portal_logo: DF.AttachImage | None
		portal_primary_color: DF.Color | None
		portal_secondary_color: DF.Color | None
		portal_secured_loans: DF.Table[PortalSecuredLoan]
		portal_support_email: DF.Data | None
		sale_charge: DF.Link | None
	# end: auto-generated types

	def validate(self):
		self.validate_portal_secured_loans()

	def on_update(self):
		sync_portal_pages()

	def validate_portal_secured_loans(self):
		seen = set()
		for row in self.portal_secured_loans:
			if row.collateral in seen:
				frappe.throw(
					_("Row {0}: {1} already has a loan product").format(row.idx, frappe.bold(_(row.collateral)))
				)
			seen.add(row.collateral)


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
		wanted = apply_on if page.route in PUBLIC_APPLY_ROUTES else portal_on
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
