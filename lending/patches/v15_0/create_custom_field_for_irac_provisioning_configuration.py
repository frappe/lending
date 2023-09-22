# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "irac_provisioning_configuraton",
					"label": "IRAC Provisioning Configuraton",
					"fieldtype": "Table",
					"options": "Loan IRAC Provisioning Configuraton",
					"insert_after": "asset_classification_ranges",
				},
			]
		},
		ignore_validate=True,
	)
