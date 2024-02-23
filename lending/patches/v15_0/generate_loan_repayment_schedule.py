# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	loans_created = frappe.db.count("Loan")

	if not loans_created:
		return

	loan_repayment_schedules_already_created = frappe.db.count("Loan Repayment Schedule")

	if loan_repayment_schedules_already_created:
		return

	for loan in frappe.get_all("Loan", filters={"is_term_loan": 1, "docstatus": ["!=", 2]}):
		loan_doc = frappe.get_cached_doc("Loan", loan.name)
		loan_repayment_schedule = frappe.new_doc("Loan Repayment Schedule")
		loan_repayment_schedule.flags.ignore_validate = True
		loan_repayment_schedule.loan = loan_doc.name
		loan_repayment_schedule.loan_product = frappe.db.get_value("Loan", loan_doc.name, "loan_type")
		loan_repayment_schedule.loan_amount = loan_doc.loan_amount
		loan_repayment_schedule.monthly_repayment_amount = loan_doc.monthly_repayment_amount
		loan_repayment_schedule.posting_date = loan_doc.posting_date
		loan_repayment_schedule.status = get_status(loan_doc.status)

		repayment_schedules = frappe.db.get_all(
			"Repayment Schedule", {"parent": loan_doc.name}, "*", order_by="idx"
		)

		for rs in repayment_schedules:
			rs.parent = loan_repayment_schedule.name
			rs.parenttype = "Loan Repayment Schedule"

		loan_repayment_schedule.set("repayment_schedule", repayment_schedules)

		loan_repayment_schedule.submit()


def get_status(loan_status):
	return {
		"Sanctioned": "Initiated",
		"Disbursed": "Active",
		"Draft": "Draft",
		"Cancelled": "Cancelled",
		"Rejected": "Rejected",
	}.get(loan_status)
