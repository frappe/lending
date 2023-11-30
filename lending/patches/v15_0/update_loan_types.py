# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	loan_products_created = frappe.db.count("Loan Product")

	if not loan_products_created:
		return

	accounts_already_updated = frappe.db.get_value(
		"Loan Product", {"disabled": 0}, "interest_receivable_account"
	)

	if accounts_already_updated:
		return

	for loan_product in frappe.db.get_all(
		"Loan Product", fields=["name", "payment_account", "loan_account", "interest_income_account"]
	):
		frappe.db.set_value(
			"Loan Product",
			loan_product.name,
			{
				"interest_receivable_account": loan_product.loan_account,
				"penalty_receivable_account": loan_product.loan_account,
				"suspense_interest_receivable": loan_product.loan_account,
				"suspense_interest_income": loan_product.interest_income_account,
				"suspense_collection_account": loan_product.payment_account,
			},
		)
