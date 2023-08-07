from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

LOAN_CUSTOM_FIELDS = {
	"Sales Invoice": [{
		"fieldname": "loan",
		"label": "loan",
		"fieldtype": "Link",
		"options": "Loan",
		"insert_after": "customer",
		"print_hide": 1,
		"read_only": 1
	}]
}

def after_install():
	create_custom_fields(LOAN_CUSTOM_FIELDS, ignore_validate=True)