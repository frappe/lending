from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Journal Entry": [
				{
					"fieldname": "loan_transfer",
					"fieldtype": "Link",
					"label": "Loan Transfer",
					"insert_after": "naming_series",
					"options": "Loan Transfer",
					"search_index": 1,
				},
				{
					"fieldname": "loan",
					"fieldtype": "Link",
					"label": "Loan",
					"insert_after": "loan_transfer",
					"options": "Loan",
					"search_index": 1,
				},
			],
		}
	)
