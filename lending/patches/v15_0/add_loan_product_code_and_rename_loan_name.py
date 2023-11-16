# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	try:
		rename_field("Loan Product", "loan_name", "product_name", validate=False)

	except Exception as e:
		if e.args[0] != 1054:
			raise

	for loan_product in frappe.db.get_all("Loan Product", fields=["name", "product_name"]):
		frappe.db.set_value("Loan Product", loan_product.name, "product_code", loan_product.product_name)
