# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from frappe.model.utils.rename_field import rename_field


def execute():
	try:
		rename_field("Loan Partner Shareable", "charge_type", "shareable_type")

	except Exception as e:
		if e.args[0] != 1054:
			raise
