# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "loan_tab",
					"fieldtype": "Tab Break",
					"label": "Loan",
					"insert_after": "expenses_included_in_valuation",
				},
			]
		},
		ignore_validate=True,
	)

	if frappe.db.exists("Custom Field", {"name": "Company-loan_settings"}):
		frappe.db.set_value(
			"Custom Field", {"name": "Company-loan_settings"}, "insert_after", "loan_tab"
		)
