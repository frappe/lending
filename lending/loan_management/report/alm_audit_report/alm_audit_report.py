# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Sum


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	columns = [
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 160},
		{
			"label": _("Loan Product"),
			"fieldname": "loan_product",
			"fieldtype": "Link",
			"options": "Loan Product",
			"width": 100,
		},
		{
			"label": _("Ageing"),
			"fieldname": "Ageing",
			"fieldtype": "Data",
			"width": 300,
		},
		{
			"label": _("Principal Amount"),
			"fieldname": "accrued_principal",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Interest Amount"),
			"fieldname": "accrued_interest",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Penalty Amount"),
			"fieldname": "penalty_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Total"),
			"fieldname": "total",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
	]

	return columns


def get_data(filters):
	data = []

	filter_obj = {
		"status": ("!=", "Closed"),
		"docstatus": 1,
	}
	if filters.get("company"):
		filter_obj.update({"company": filters.get("company")})

	demand_details, loan_product_map = get_overdue_details(
		filters.get("as_on_date"), filters.get("company")
	)
	for loan, amounts in demand_details.items():
		data.append(
			{
				"loan": loan,
				"loan_product": loan_product_map.get(loan),
				"accrued_principal": amounts.get("total_pending_principal"),
				"accrued_interest": amounts.get("total_pending_interest"),
				"penalty_amount": amounts.get("total_pending_penalty"),
				"total": amounts.get("total_pending_principal")
				+ amounts.get("total_pending_interest")
				+ amounts.get("total_pending_penalty"),
			}
		)

	return data


def get_overdue_details(as_on_date, company):
	loan_demand = frappe.qb.DocType("Loan Demand")
	query = (
		frappe.qb.from_(loan_demand)
		.select(
			loan_demand.loan,
			loan_demand.loan_product,
			loan_demand.demand_type,
			loan_demand.demand_subtype,
			Sum(loan_demand.outstanding_amount).as_("outstanding_amount"),
		)
		.where(
			(loan_demand.docstatus == 1)
			& (loan_demand.company == company)
			& (loan_demand.demand_date <= as_on_date)
			& (loan_demand.outstanding_amount > 0)
			& (loan_demand.demand_type != "Charges")
		)
		.groupby(loan_demand.loan, loan_demand.demand_type, loan_demand.demand_subtype)
	)

	loan_demands = query.run(as_dict=1)

	overdue_details = {}
	loan_product_map = {}

	for demand in loan_demands:
		loan_product_map[demand.loan] = demand.loan_product
		overdue_details.setdefault(
			demand.loan,
			{
				"total_pending_principal": 0.0,
				"total_pending_interest": 0.0,
				"total_pending_penalty": 0.0,
			},
		)

		if demand.demand_subtype == "Interest":
			overdue_details[demand.loan]["total_pending_interest"] += demand.outstanding_amount
		elif demand.demand_subtype == "Principal":
			overdue_details[demand.loan]["total_pending_principal"] += demand.outstanding_amount
		elif demand.demand_subtype == "Penalty":
			overdue_details[demand.loan]["total_pending_penalty"] += demand.outstanding_amount

	return overdue_details, loan_product_map
