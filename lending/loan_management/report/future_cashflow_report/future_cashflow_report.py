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
			"width": 150,
		},
		{
			"label": _("Loan Disbursement"),
			"fieldname": "loan_disbursement",
			"fieldtype": "Link",
			"options": "Loan Disbursement",
			"width": 150,
		},
		{
			"label": _("Applicant Name"),
			"fieldname": "applicant",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Loan Product"),
			"fieldname": "loan_product",
			"fieldtype": "Link",
			"options": "Loan Product",
			"width": 150,
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
	Loan = frappe.qb.DocType("Loan")
	LoanRepaymentSchedule = frappe.qb.DocType("Loan Repayment Schedule")
	RepaymentSchedule = frappe.qb.DocType("Repayment Schedule")
	LoanDisbursement = frappe.qb.DocType("Loan Disbursement")

	query = (
		frappe.qb.from_(Loan)
		.join(LoanDisbursement)
		.on(LoanDisbursement.against_loan == Loan.name)
		.join(LoanRepaymentSchedule)
		.on(LoanRepaymentSchedule.loan_disbursement == LoanDisbursement.name)
		.join(RepaymentSchedule)
		.on(
			(RepaymentSchedule.parent == LoanRepaymentSchedule.name)
			& (RepaymentSchedule.parentfield == "repayment_schedule")
		)
		.select(
			Loan.name.as_("loan"),
			LoanDisbursement.name.as_("loan_disbursement"),
			Loan.applicant,
			Loan.loan_product,
			RepaymentSchedule.payment_date,
			RepaymentSchedule.principal_amount,
			RepaymentSchedule.interest_amount,
			RepaymentSchedule.total_payment,
		)
		.where(Loan.docstatus == 1)
		.where(LoanRepaymentSchedule.docstatus == 1)
		.where(LoanRepaymentSchedule.status == "Active")
		.where(Loan.status.isin(["Disbursed", "Partially Disbursed", "Active"]))
		.where(Loan.freeze_account == 0)
		.where(RepaymentSchedule.payment_date >= filters.get("as_on_date"))
		.where(RepaymentSchedule.demand_generated == 0)
		.where(LoanDisbursement.docstatus == 1)
	)

	if filters.get("company"):
		query = query.where(Loan.company == filters.get("company"))
	if filters.get("loan_product"):
		query = query.where(Loan.loan_product == filters.get("loan_product"))
	if filters.get("loan"):
		query = query.where(Loan.name == filters.get("loan"))
	if filters.get("loan_disbursement"):
		query = query.where(LoanDisbursement.name == filters.get("loan_disbursement"))

	query = query.orderby(RepaymentSchedule.payment_date)

	return query.run(as_dict=True)
