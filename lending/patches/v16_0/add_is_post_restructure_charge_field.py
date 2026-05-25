import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("Custom Field", {"dt": "Sales Invoice", "fieldname": "is_post_restructure_charge"}):
		custom_fields = {
			"Sales Invoice": [
				{
					"fieldname": "is_post_restructure_charge",
					"label": "Is Post Restructure Charge",
					"fieldtype": "Check",
					"insert_after": "loan_repayment",
					"read_only": 1,
				}
			]
		}
		create_custom_fields(custom_fields, update=True)
