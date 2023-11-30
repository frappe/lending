# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	try:
		if frappe.db.has_column("Loan", "loan_type"):
			rename_field("Loan", "loan_type", "loan_product")
		if frappe.db.has_column("Loan Application", "loan_type"):
			rename_field("Loan Application", "loan_type", "loan_product")
		if frappe.db.has_column("Loan Disbursement", "loan_type"):
			rename_field("Loan Disbursement", "loan_type", "loan_product")
		if frappe.db.has_column("Loan Interest Accrual", "loan_type"):
			rename_field("Loan Interest Accrual", "loan_type", "loan_product")
		if frappe.db.has_column("Loan Repayment", "loan_type"):
			rename_field("Loan Repayment", "loan_type", "loan_product")
		if frappe.db.has_column("Loan Repayment Schedule", "loan_type"):
			rename_field("Loan Repayment Schedule", "loan_type", "loan_product")
		if frappe.db.has_column("Loan Restructure", "loan_type"):
			rename_field("Loan Restructure", "loan_type", "loan_product")
		if frappe.db.has_column("Process Loan Classification", "loan_type"):
			rename_field("Process Loan Classification", "loan_type", "loan_product")
		if frappe.db.has_column("Process Loan Interest Accrual", "loan_type"):
			rename_field("Process Loan Interest Accrual", "loan_type", "loan_product")

	except Exception as e:
		if e.args[0] != 1054:
			raise
