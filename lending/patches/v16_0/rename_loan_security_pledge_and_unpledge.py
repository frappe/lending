# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe


def execute():
	if frappe.db.exists("DocType", "Loan Security Pledge") and not frappe.db.exists(
		"DocType", "Loan Security Assignment"
	):
		frappe.rename_doc("DocType", "Loan Security Pledge", "Loan Security Assignment", force=True)

	if frappe.db.exists("DocType", "Loan Security Unpledge") and not frappe.db.exists(
		"DocType", "Loan Security Release"
	):
		frappe.rename_doc("DocType", "Loan Security Unpledge", "Loan Security Release", force=True)
