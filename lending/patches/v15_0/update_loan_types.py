# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	for loan_type in frappe.db.get_all(
		"Loan Type", fields=["name", "payment_account", "loan_account", "interest_income_account"]
	):
		frappe.db.set_value(
			"Loan Type",
			loan_type.name,
			{
				"interest_receivable_account": loan_type.loan_account,
				"charges_receivable_account": loan_type.loan_account,
				"penalty_receivable_account": loan_type.loan_account,
				"suspense_interest_receivable": loan_type.loan_account,
				"suspense_interest_income": loan_type.interest_income_account,
				"suspense_collection_account": loan_type.payment_account,
			},
		)
