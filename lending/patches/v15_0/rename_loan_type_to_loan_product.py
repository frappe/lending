# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.model.rename_doc import rename_doc


def execute():
	if frappe.db.table_exists("Loan Type"):
		frappe.db.sql_ddl("DROP TABLE `tabLoan Product`")

		rename_doc(
			doctype="DocType",
			old="Loan Type",
			new="Loan Product",
			force=True,
			validate=False,
		)

		frappe.reload_doc("loan_management", "doctype", "loan_product", force=True)
