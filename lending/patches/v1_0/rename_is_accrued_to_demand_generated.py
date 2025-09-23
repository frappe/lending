import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	if not frappe.db.has_column("Repayment Schedule", "demand_generated"):
		rename_field("Repayment Schedule", "is_accrued", "demand_generated")
