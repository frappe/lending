# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe


def execute():
	if frappe.db.exists("Custom Field", {"name": "Company-asset_classification_ranges"}):
		frappe.db.set_value(
			"Custom Field",
			{"name": "Company-asset_classification_ranges"},
			"label",
			"Loan Asset Classification Ranges",
		)
