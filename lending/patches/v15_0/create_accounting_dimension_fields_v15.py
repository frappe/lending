import frappe

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	create_accounting_dimensions_for_doctype,
)


def execute():
	doctypes = frappe.get_hooks("accounting_dimension_doctypes", app_name="lending")

	for doctype in doctypes:
		create_accounting_dimensions_for_doctype(doctype)
