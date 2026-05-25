import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	company_fields = []
	created_demand_queue_field = False
	created_interest_queue_field = False

	if not frappe.db.exists(
		"Custom Field", {"dt": "Company", "fieldname": "enable_demand_cancel_gl_queue"}
	):
		company_fields.append(
			{
				"fieldname": "enable_demand_cancel_gl_queue",
				"label": "Enable Demand Cancel GL Queue",
				"fieldtype": "Check",
				"default": "1",
				"insert_after": "enable_loan_accounting",
			}
		)
		created_demand_queue_field = True

	if not frappe.db.exists(
		"Custom Field", {"dt": "Company", "fieldname": "enable_interest_cancel_gl_queue"}
	):
		company_fields.append(
			{
				"fieldname": "enable_interest_cancel_gl_queue",
				"label": "Enable Interest Cancel GL Queue",
				"fieldtype": "Check",
				"default": "1",
				"insert_after": "enable_demand_cancel_gl_queue",
			}
		)
		created_interest_queue_field = True

	if company_fields:
		create_custom_fields({"Company": company_fields}, update=True)

	if created_demand_queue_field:
		frappe.db.sql(
			"""
			update `tabCompany`
			set enable_demand_cancel_gl_queue = 1
			where ifnull(enable_demand_cancel_gl_queue, 0) = 0
			"""
		)

	if created_interest_queue_field:
		frappe.db.sql(
			"""
			update `tabCompany`
			set enable_interest_cancel_gl_queue = 1
			where ifnull(enable_interest_cancel_gl_queue, 0) = 0
			"""
		)
