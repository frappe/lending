from frappe.model.utils.rename_field import rename_field


def execute():
	# Rename the field and keep data intact
	rename_field("Repayment Schedule", "is_accrued", "demand_generated")
