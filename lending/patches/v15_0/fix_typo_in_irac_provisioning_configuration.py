# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if frappe.db.table_exists("Loan IRAC Provisioning Configuraton") and not frappe.db.table_exists(
		"Loan IRAC Provisioning Configuration"
	):
		frappe.rename_doc(
			"DocType",
			"Loan IRAC Provisioning Configuraton",
			"Loan IRAC Provisioning Configuration",
			force=True,
		)
		frappe.reload_doc("loan_management", "doctype", "loan_irac_provisioning_configuration")

	if frappe.db.exists("Custom Field", "Company-irac_provisioning_configuraton"):
		frappe.delete_doc("Custom Field", "Company-irac_provisioning_configuraton")

		create_custom_fields(
			{
				"Company": [
					{
						"fieldname": "irac_provisioning_configuration",
						"label": "IRAC Provisioning Configuration",
						"fieldtype": "Table",
						"options": "Loan IRAC Provisioning Configuration",
						"insert_after": "loan_classification_ranges",
					},
				]
			},
			ignore_validate=True,
		)

		ipc = frappe.qb.DocType("Loan IRAC Provisioning Configuration")
		frappe.qb.update(ipc).set(ipc.parentfield, "irac_provisioning_configuration").run()
