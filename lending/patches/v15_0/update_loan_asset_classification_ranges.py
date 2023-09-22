# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from frappe.model.utils.rename_field import rename_field


def execute():
	try:
		rename_field("Loan Classification Range", "min_range", "min_dpd_range")
		rename_field("Loan Classification Range", "max_range", "max_dpd_range")
		rename_field("Loan Classification Range", "asset_classification_code", "classification_code")
		rename_field("Loan Classification Range", "asset_classification_name", "classification_name")

	except Exception as e:
		if e.args[0] != 1054:
			raise
