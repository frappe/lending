# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "interest_day_count_convention",
					"label": "Interest Day-Count Convention",
					"fieldtype": "Select",
					"options": "Actual/365\nActual/Actual\n30/365\n30/360\nActual/360",
					"insert_after": "watch_period_post_loan_restructure_in_days",
				},
			]
		},
		ignore_validate=True,
	)

	if frappe.db.exists("Custom Field", {"name": "Company-loan_column_break"}):
		frappe.db.set_value(
			"Custom Field",
			{"name": "Company-loan_column_break"},
			"insert_after",
			"interest_day_count_convention",
		)
