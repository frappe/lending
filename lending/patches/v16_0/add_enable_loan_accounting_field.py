import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("Custom Field", {"dt": "Company", "fieldname": "enable_loan_accounting"}):
		custom_fields = {
			"Company": [
				{
					"fieldname": "enable_loan_accounting",
					"label": "Enable Loan Accounting",
					"fieldtype": "Check",
					"insert_after": "loan_column_break",
				}
			]
		}
		create_custom_fields(custom_fields, update=True)

	companies = frappe.get_all("Company", pluck="name")
	for company in companies:
		frappe.db.set_value("Company", company, "enable_loan_accounting", 1)