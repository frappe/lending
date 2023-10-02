# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from frappe.model.utils.rename_field import rename_field


def execute():
	try:
		rename_field("Loan", "loan_type", "loan_product")
		rename_field("Loan Application", "loan_type", "loan_product")
		rename_field("Loan Disbursement", "loan_type", "loan_product")
		rename_field("Loan Interest Accrual", "loan_type", "loan_product")
		rename_field("Loan IRAC Provisioning Configuration", "loan_type", "loan_product")
		rename_field("Loan Repayment", "loan_type", "loan_product")
		rename_field("Loan Repayment Schedule", "loan_type", "loan_product")
		rename_field("Loan Restructure", "loan_type", "loan_product")
		rename_field("Process Loan Classification", "loan_type", "loan_product")
		rename_field("Process Loan Interest Accrual", "loan_type", "loan_product")

	except Exception as e:
		if e.args[0] != 1054:
			raise
