# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	columns = get_columns()
	data = get_loan_report_data(filters)
	return columns, data


def get_columns():
	columns = [
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 160},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 160},
		{"label": _("Applicant Type"), "fieldname": "applicant_type", "fieldtype": "Data", "width": 100},
		{
			"label": _("Applicant Name"),
			"fieldname": "applicant_name",
			"fieldtype": "Dynamic Link",
			"options": "applicant_type",
			"width": 150,
		},
		{
			"label": _("Loan Product"),
			"fieldname": "loan_product",
			"fieldtype": "Link",
			"options": "Loan Product",
			"width": 100,
		},
		{
			"label": _("Principal Demand Amount"),
			"fieldname": "principal_demand_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Principal Paid Amount"),
			"fieldname": "principal_paid_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Principal Outstanding Amount"),
			"fieldname": "principal_outstanding_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Interest Demand Amount"),
			"fieldname": "interest_demand_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Interest Paid Amount"),
			"fieldname": "interest_paid_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Interest Outstanding Amount"),
			"fieldname": "interest_outstanding_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Penalty Demand Amount"),
			"fieldname": "penalty_demand_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Penalty Paid Amount"),
			"fieldname": "penalty_paid_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Penalty Outstanding Amount"),
			"fieldname": "penalty_outstanding_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Additional Interest Demand Amount"),
			"fieldname": "additional_interest_demand_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Additional Interest Paid Amount"),
			"fieldname": "additional_interest_paid_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Additional Interest Outstanding Amount"),
			"fieldname": "additional_interest_outstanding_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Rate of Interest"),
			"fieldname": "rate_of_interest",
			"fieldtype": "Percent",
			"width": 100,
		},
		{
			"label": _("Interest Amount"),
			"fieldname": "interest_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Total Repayment"),
			"fieldname": "total_repayment",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Total Outstanding"),
			"fieldname": "total_outstanding",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
	]
	return columns


def get_loan_report_data(filters):
	loan_details = get_active_loan_details(filters)
	return loan_details


def get_active_loan_details(filters):
	loan = frappe.qb.DocType("Loan")
	filter_obj = (loan.status != "Closed") & (loan.docstatus == 1)

	for field in ("company", "applicant_type", "applicant", "name", "loan_product"):
		if filters.get(field):
			filter_obj &= loan[field] == filters.get(field)

	query = (
		frappe.qb.from_(loan)
		.select(
			loan.name.as_("loan"),
			loan.applicant_type,
			loan.applicant.as_("applicant_name"),
			loan.loan_product,
			loan.status,
		)
		.where(filter_obj)
	)
	loan_details = query.run(as_dict=True)

	as_on_date = filters.get("as_on_date")

	for loan in loan_details:
		demand_details = get_loan_demand_details(loan["loan"], as_on_date)
		interest_accruals = get_interest_accruals(loan["loan"])

		loan.update(
			{
				"principal_demand_amount": flt(demand_details.get("principal_demand_amount")),
				"principal_paid_amount": flt(demand_details.get("principal_paid_amount")),
				"principal_outstanding_amount": flt(demand_details.get("principal_outstanding_amount")),
				"interest_demand_amount": flt(demand_details.get("interest_demand_amount")),
				"interest_paid_amount": flt(demand_details.get("interest_paid_amount")),
				"interest_outstanding_amount": flt(demand_details.get("interest_outstanding_amount")),
				"penalty_demand_amount": flt(demand_details.get("penalty_demand_amount")),
				"penalty_paid_amount": flt(demand_details.get("penalty_paid_amount")),
				"penalty_outstanding_amount": flt(demand_details.get("penalty_outstanding_amount")),
				"additional_interest_demand_amount": flt(
					demand_details.get("additional_interest_demand_amount")
				),
				"additional_interest_paid_amount": flt(demand_details.get("additional_interest_paid_amount")),
				"additional_interest_outstanding_amount": flt(
					demand_details.get("additional_interest_outstanding_amount")
				),
				"rate_of_interest": flt(interest_accruals.get("rate_of_interest")),
				"interest_amount": flt(interest_accruals.get("interest_amount")),
				"total_repayment": flt(
					demand_details.get("principal_paid_amount") + demand_details.get("interest_paid_amount")
				),
				"total_outstanding": flt(demand_details.get("principal_outstanding_amount"))
				+ flt(demand_details.get("interest_outstanding_amount")),
			}
		)

	return loan_details


def get_loan_demand_details(loan_name, as_on_date):
	loan_demand = frappe.qb.DocType("Loan Demand")
	query = (
		frappe.qb.from_(loan_demand)
		.select(
			loan_demand.demand_subtype,
			loan_demand.demand_amount,
			loan_demand.paid_amount,
			loan_demand.outstanding_amount,
		)
		.where((loan_demand.loan == loan_name) & (loan_demand.demand_date <= as_on_date))
	)
	demands = query.run(as_dict=True)

	totals = {
		"principal_demand_amount": 0.0,
		"principal_paid_amount": 0.0,
		"principal_outstanding_amount": 0.0,
		"interest_demand_amount": 0.0,
		"interest_paid_amount": 0.0,
		"interest_outstanding_amount": 0.0,
		"penalty_demand_amount": 0.0,
		"penalty_paid_amount": 0.0,
		"penalty_outstanding_amount": 0.0,
		"additional_interest_demand_amount": 0.0,
		"additional_interest_paid_amount": 0.0,
		"additional_interest_outstanding_amount": 0.0,
	}

	for demand in demands:
		if demand["demand_subtype"] == "Principal":
			totals["principal_demand_amount"] += flt(demand["demand_amount"])
			totals["principal_paid_amount"] += flt(demand["paid_amount"])
			totals["principal_outstanding_amount"] += flt(demand["outstanding_amount"])
		elif demand["demand_subtype"] == "Interest":
			totals["interest_demand_amount"] += flt(demand["demand_amount"])
			totals["interest_paid_amount"] += flt(demand["paid_amount"])
			totals["interest_outstanding_amount"] += flt(demand["outstanding_amount"])
		elif demand["demand_subtype"] == "Penalty":
			totals["penalty_demand_amount"] += flt(demand["demand_amount"])
			totals["penalty_paid_amount"] += flt(demand["paid_amount"])
			totals["penalty_outstanding_amount"] += flt(demand["outstanding_amount"])
		elif demand["demand_subtype"] == "Additional Interest":
			totals["additional_interest_demand_amount"] += flt(demand["demand_amount"])
			totals["additional_interest_paid_amount"] += flt(demand["paid_amount"])
			totals["additional_interest_outstanding_amount"] += flt(demand["outstanding_amount"])

	return totals


def get_interest_accruals(loan_name):
	loan_interest_accrual = frappe.qb.DocType("Loan Interest Accrual")
	query = (
		frappe.qb.from_(loan_interest_accrual)
		.select(loan_interest_accrual.interest_amount, loan_interest_accrual.rate_of_interest)
		.where(loan_interest_accrual.loan == loan_name)
		.orderby(loan_interest_accrual.posting_date, order=frappe.qb.desc)
		.limit(1)
	)
	interest_accruals = query.run(as_dict=True)

	if interest_accruals:
		return interest_accruals[0]
	else:
		return {"interest_amount": 0, "rate_of_interest": 0}
