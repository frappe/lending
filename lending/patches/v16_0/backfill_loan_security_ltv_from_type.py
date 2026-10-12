import frappe
from frappe.utils import flt


def execute():
	type_ltv = dict(frappe.get_all("Loan Security Type", fields=["name", "loan_to_value_ratio"], as_list=1))

	for security in frappe.get_all(
		"Loan Security", fields=["name", "loan_security_type", "loan_to_value_ratio"]
	):
		ltv = flt(type_ltv.get(security.loan_security_type))
		if flt(security.loan_to_value_ratio) or not ltv:
			continue

		frappe.db.set_value(
			"Loan Security", security.name, "loan_to_value_ratio", ltv, update_modified=False
		)
