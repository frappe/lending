# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

def execute():
	for loan in frappe.get_all("Loan", filters={"is_term_loan": 1}):
		loan = frappe.get_cached_doc("Loan", loan.name)
		loan_repayment_schedule = frappe.new_doc("Loan Repayment Schedule")
		loan_repayment_schedule.flags.ignore_validate = True
		loan_repayment_schedule.loan = loan.name
		loan_repayment_schedule.posting_date = loan.posting_date
		loan_repayment_schedule.set("repayment_schedule", loan.repayment_schedule)
		loan_repayment_schedule.status = get_status(loan.status)
		loan_repayment_schedule.submit()


def get_status(loan_status):
	return {
		"Sanctioned": "Initiated",
		"Disbursed": "Active",
		"Draft": "Draft",
		"Cancelled": "Cancelled",
		"Rejected": "Rejected",
	}.get(loan_status)