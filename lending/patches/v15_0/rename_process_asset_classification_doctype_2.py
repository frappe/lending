# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe


def execute():
	if frappe.db.table_exists("Process Loan Asset Classification") and not frappe.db.table_exists(
		"Process Loan Classification"
	):
		frappe.rename_doc(
			"DocType", "Process Loan Asset Classification", "Process Loan Classification", force=True
		)
		frappe.reload_doc("loan_management", "doctype", "process_loan_classification")
