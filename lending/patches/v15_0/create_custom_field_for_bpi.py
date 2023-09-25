# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "min_bpi_application_days",
					"label": "Minimum Days for Broken Period Interest Application",
					"fieldtype": "Int",
					"insert_after": "interest_day_count_convention",
				},
			]
		},
		ignore_validate=True,
	)
