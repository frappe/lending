# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe


def execute():
	loan_products_created = frappe.db.count("Loan Product")

	if not loan_products_created:
		return

	for loan_product in frappe.db.get_all("Loan Product", fields=["name"]):
		frappe.db.set_value("Loan Product", loan_product.name, "penalty_interest_method", "Rate")
