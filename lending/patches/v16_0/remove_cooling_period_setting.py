import frappe

REMOVED_SETTINGS_FIELDS = ["cooling_period_days"]


def execute():
	frappe.db.delete(
		"Singles",
		{
			"doctype": "Loan Origination Settings",
			"field": ["in", REMOVED_SETTINGS_FIELDS],
		},
	)
