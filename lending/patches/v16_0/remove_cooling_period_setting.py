import frappe

# A Single keeps its values in tabSingles, so a removed field leaves its row behind.
REMOVED_SETTINGS_FIELDS = ["cooling_period_days"]


def execute():
	frappe.db.delete(
		"Singles",
		{
			"doctype": "Loan Origination Settings",
			"field": ["in", REMOVED_SETTINGS_FIELDS],
		},
	)
