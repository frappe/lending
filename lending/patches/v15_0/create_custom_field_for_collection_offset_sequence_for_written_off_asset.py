# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "collection_offset_sequence_for_written_off_asset",
					"label": "Collection Offset Sequence for Written Off Asset",
					"fieldtype": "Select",
					"options": "IP...IP...IP...CCC\nPPP...III...CCC",
					"insert_after": "collection_offset_sequence_for_standard_asset",
				},
			]
		},
		ignore_validate=True,
	)

	frappe.db.set_value(
		"Custom Field",
		{"name": "Company-loan_section_break_2"},
		"insert_after",
		"collection_offset_sequence_for_written_off_asset",
	)
