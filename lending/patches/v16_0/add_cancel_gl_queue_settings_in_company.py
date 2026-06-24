import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	company_fields = [
		{
			"fieldname": "enable_async_gl_reversal",
			"label": "Enable async reversal of GL for future demand and accruals",
			"fieldtype": "Check",
			"insert_after": "enable_loan_accounting",
		},
		{
			"fieldname": "async_gl_reversal_start_date",
			"label": "Async GL Reversal Start Date",
			"fieldtype": "Date",
			"depends_on": "enable_async_gl_reversal",
			"mandatory_depends_on": "enable_async_gl_reversal",
			"insert_after": "enable_async_gl_reversal",
		},
	]

	create_custom_fields({"Company": company_fields}, update=True)

	for doctype in ("Loan Demand", "Loan Interest Accrual"):
		table = frappe.qb.DocType(doctype)
		frappe.qb.update(table).set(table.is_gl_cancelled, 1).where(table.docstatus == 2).run()
