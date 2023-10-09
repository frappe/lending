# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe


def execute():
	for loan_product in frappe.db.get_all("Loan Product", fields=["name"]):
		frappe.db.set_value("Loan Product", loan_product.name, "penalty_interest_method", "Rate")
