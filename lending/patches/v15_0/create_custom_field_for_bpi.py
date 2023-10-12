# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "min_days_bw_disbursement_first_repayment",
					"label": "Minimum days between Disbursement date and first Repayment date",
					"fieldtype": "Int",
					"insert_after": "interest_day_count_convention",
					"non_negative": 1,
				},
			]
		},
		ignore_validate=True,
	)
