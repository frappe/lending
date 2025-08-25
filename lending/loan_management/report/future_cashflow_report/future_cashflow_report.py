# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"label": _("Loan"),
			"fieldname": "loan",
			"fieldtype": "Link",
			"options": "Loan",
			"width": 200,
		},
		{
			"label": _("Loan Disbursement"),
			"fieldname": "loan_disbursement",
			"fieldtype": "Link",
			"options": "Loan Disbursement",
			"width": 180,
		},
		{
			"label": _("Loan Product"),
			"fieldname": "loan_product",
			"fieldtype": "Link",
			"options": "Loan Product",
			"width": 180,
		},
		{
			"label": _("Payment Date"),
			"fieldname": "payment_date",
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"label": _("Principal Amount"),
			"fieldname": "principal_amount",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Interest Amount"),
			"fieldname": "interest_amount",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Total Payment"),
			"fieldname": "total_payment",
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def get_data(filters):
	if not filters.get("company"):
		frappe.throw(_("Please select Company."))
	if not filters.get("as_on_date"):
		frappe.throw(_("Please select As on Date."))

	LoanRepaymentSchedule = frappe.qb.DocType("Loan Repayment Schedule")
	RepaymentSchedule = frappe.qb.DocType("Repayment Schedule")

	query = (
		frappe.qb.from_(LoanRepaymentSchedule)
		.join(RepaymentSchedule)
		.on(
			(RepaymentSchedule.parent == LoanRepaymentSchedule.name)
			& (RepaymentSchedule.parentfield == "repayment_schedule")
		)
		.select(
			LoanRepaymentSchedule.loan,
			LoanRepaymentSchedule.loan_disbursement,
			LoanRepaymentSchedule.loan_product,
			LoanRepaymentSchedule.company,
			RepaymentSchedule.payment_date,
			RepaymentSchedule.principal_amount,
			RepaymentSchedule.interest_amount,
			RepaymentSchedule.total_payment,
		)
		.where(LoanRepaymentSchedule.docstatus == 1)
		.where(LoanRepaymentSchedule.status == "Active")
		.where(RepaymentSchedule.payment_date >= filters.get("as_on_date"))
		.where(RepaymentSchedule.demand_generated == 0)
	)

	if filters.get("company"):
		query = query.where(LoanRepaymentSchedule.company == filters.get("company"))
	if filters.get("loan_product"):
		query = query.where(LoanRepaymentSchedule.loan_product == filters.get("loan_product"))
	if filters.get("loan"):
		query = query.where(LoanRepaymentSchedule.loan == filters.get("loan"))
	if filters.get("loan_disbursement"):
		query = query.where(LoanRepaymentSchedule.loan_disbursement == filters.get("loan_disbursement"))

	query = query.orderby(RepaymentSchedule.payment_date)

	return query.run(as_dict=True)
