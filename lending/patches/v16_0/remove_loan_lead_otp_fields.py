import frappe

REMOVED_LOAN_LEAD_FIELDS = ["sms_otp", "email_otp"]


def execute():
	frappe.db.delete(
		"__Auth",
		{"doctype": "Loan Lead", "fieldname": ["in", REMOVED_LOAN_LEAD_FIELDS]},
	)
