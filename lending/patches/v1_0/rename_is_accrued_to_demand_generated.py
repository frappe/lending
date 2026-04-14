import frappe


def execute():
	if frappe.db.has_column("Repayment Schedule", "is_accrued"):
		frappe.db.sql("""
			UPDATE `tabRepayment Schedule`
			SET demand_generated = is_accrued
			WHERE demand_generated IS NULL OR demand_generated = 0
		""")
