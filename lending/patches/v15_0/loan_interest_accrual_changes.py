# import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	rename_field("Repayment Schedule", "is_accrued", "demand_generated")
