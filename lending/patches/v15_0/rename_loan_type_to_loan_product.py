# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe


def execute():
	if frappe.db.table_exists("Loan Type") and not frappe.db.table_exists("Loan Product"):
		frappe.rename_doc("DocType", "Loan Type", "Loan Product", force=True)
		frappe.reload_doc("loan_management", "doctype", "loan_product")
