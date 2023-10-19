# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe


def execute():
	if frappe.db.table_exists("Loan Security Pledge") and not frappe.db.table_exists(
		"Loan Collateral Assignment"
	):
		frappe.rename_doc("DocType", "Loan Security Pledge", "Loan Collateral Assignment", force=True)
		frappe.reload_doc("loan_management", "doctype", "loan_collateral_assignment")

	if frappe.db.table_exists("Loan Security Unpledge") and not frappe.db.table_exists(
		"Loan Collateral Deassignment"
	):
		frappe.rename_doc(
			"DocType", "Loan Security Unpledge", "Loan Collateral Deassignment", force=True
		)
		frappe.reload_doc("loan_management", "doctype", "loan_collateral_deassignment")
