# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	frappe.delete_doc("Custom Field", "Company-asset_classification_ranges")

	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "loan_classification_ranges",
					"label": "Loan Classification Ranges",
					"fieldtype": "Table",
					"options": "Loan Classification Range",
					"insert_after": "loan_section_break_2",
				},
			]
		},
		ignore_validate=True,
	)

	lcr = frappe.qb.DocType("Loan Classification Range")
	frappe.qb.update(lcr).set(lcr.parentfield, "loan_classification_ranges").run()

	frappe.db.set_value(
		"Custom Field",
		{"name": "Company-irac_provisioning_configuration"},
		"insert_after",
		"loan_classification_ranges",
	)
