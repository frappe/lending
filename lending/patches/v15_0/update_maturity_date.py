import frappe


def execute():
	loan_filters = {
		"status": ("in", ["Disbursed", "Partially Disbursed", "Active", "Written Off"]),
		"docstatus": 1,
	}

	open_loans = frappe.get_all(
		"Loan",
		filters=loan_filters,
		pluck="name",
	)

	schedule_filters = {"loan": ("in", open_loans), "docstatus": 1, "status": "Active"}

	schedules = frappe.db.get_all(
		"Loan Repayment Schedule",
		filters=schedule_filters,
		pluck="name",
	)

	for schedule in schedules:
		maturity_date = get_maturity_date(schedule)
		if maturity_date:
			frappe.db.set_value(
				"Loan Repayment Schedule", schedule, "maturity_date", maturity_date, update_modified=False
			)


def get_maturity_date(schedule):
	maturity_date = frappe.db.get_value(
		"Repayment Schedule",
		{"parent": schedule},
		"MAX(payment_date)",
	)

	return maturity_date
