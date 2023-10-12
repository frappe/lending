# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("Custom Field", "Company-min_bpi_application_days") and frappe.db.exists(
		"Custom Field", "Company-min_days_bw_disbursement_first_repayment"
	):
		return

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

	frappe.db.set_value(
		"Custom Field",
		{"name": "Company-loan_column_break"},
		"insert_after",
		"min_days_bw_disbursement_first_repayment",
	)

	for company in frappe.db.get_all("Company", fields=["name", "min_bpi_application_days"]):
		frappe.db.set_value(
			"Company",
			company.name,
			"min_days_bw_disbursement_first_repayment",
			company.min_bpi_application_days,
		)

	frappe.delete_doc("Custom Field", "Company-min_bpi_application_days")
