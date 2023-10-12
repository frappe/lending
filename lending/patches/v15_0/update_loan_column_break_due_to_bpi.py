# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe


def execute():
	if frappe.db.exists("Custom Field", "Company-loan_column_break"):
		frappe.db.set_value(
			"Custom Field",
			"Company-loan_column_break",
			"insert_after",
			"min_days_bw_disbursement_first_repayment",
		)
