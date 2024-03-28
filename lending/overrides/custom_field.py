import frappe

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)

from lending.hooks import accounting_dimension_doctypes


def update_dimensions(doc, method=None):
	accounting_dimensions = get_accounting_dimensions()
	if doc.fieldname in accounting_dimensions:
		if doc.dt in accounting_dimension_doctypes:
			meta = frappe.get_meta(doc.dt)
			if meta.has_field("loan"):
				update_fetch_from("loan", doc)
			elif meta.has_field("against_loan"):
				update_fetch_from("against_loan", doc)


def update_fetch_from(fieldname, custom_field):
	custom_field.fetch_from = f"{fieldname}.{custom_field.fieldname}"
