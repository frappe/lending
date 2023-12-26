import click

import frappe

from lending.install import LOAN_CUSTOM_FIELDS


def before_uninstall():
	try:
		print("Removing customizations created by the Frappe Lending app...")
		delete_custom_fields(LOAN_CUSTOM_FIELDS)

	except Exception as e:
		BUG_REPORT_URL = "https://github.com/frappe/lending/issues/new"
		click.secho(
			"Removing Customizations for Frappe Lending failed due to an error."
			" Please try again or"
			f" report the issue on {BUG_REPORT_URL} if not resolved.",
			fg="bright_red",
		)
		raise e

	click.secho("Frappe Lending app customizations have been removed successfully.", fg="green")


def delete_custom_fields(custom_fields):
	"""
	:param custom_fields: a dict like `{'Customer': [{fieldname: 'test', ...}]}`
	"""

	for doctypes, fields in custom_fields.items():
		if isinstance(fields, dict):
			# only one field
			fields = [fields]

		if isinstance(doctypes, str):
			# only one doctype
			doctypes = (doctypes,)

		for doctype in doctypes:
			frappe.db.delete(
				"Custom Field",
				{
					"fieldname": ("in", [field["fieldname"] for field in fields]),
					"dt": doctype,
				},
			)

			frappe.clear_cache(doctype=doctype)
