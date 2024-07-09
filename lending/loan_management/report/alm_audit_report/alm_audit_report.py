# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import date_diff


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	ageing_columns = get_ageing_columns()
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

	return columns[:1] + ageing_columns + columns[1:]


def get_ageing_columns():
	columns = []
	for ageing in get_ageing_list(columns=True):
		columns.append(
			{
				"label": _(frappe.unscrub(ageing)),
				"fieldname": ageing,
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	return columns


def get_ageing_list(columns=False):
	ageing_map = {
		"0-0": "overdue",
		"0-30": "0_to_1_month",
		"30-60": "1_to_2_months",
		"60-90": "2_to_3_months",
		"90-180": "3_to_6_months",
		"180-365": "6_to_12_months",
		"365-730": "1_to_2_years",
		"730-1095": "2_to_3_years",
		"1095-1460": "3_to_4_years",
		"1460-1825": "4_to_5_years",
		"1825-100000": "5_years_and_above",
	}

	if columns:
		return [value for key, value in ageing_map.items()]
	else:
		return ageing_map


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

	future_details_map, loans = get_future_interest_details(
		filters.get("as_on_date"), filters.get("company")
	)

	for loan in loans:
		amounts = demand_details.get(loan, {})
		future_details = future_details_map.get(loan, [])
		total = (
			amounts.get("total_pending_principal", 0)
			+ amounts.get("total_pending_interest", 0)
			+ amounts.get("total_pending_penalty", 0)
		)

		row = {
			"loan": loan,
			"loan_product": loan_product_map.get(loan),
			"accrued_principal": amounts.get("total_pending_principal", 0),
			"accrued_interest": amounts.get("total_pending_interest", 0),
			"penalty_amount": amounts.get("total_pending_penalty", 0),
			"overdue": total,
			"total": total,
		}

		for entry in future_details:
			ageing_bucket = get_ageing_bucket(entry.payment_date, filters.get("as_on_date"))
			row.setdefault(ageing_bucket, 0.0)
			row[ageing_bucket] += entry.interest_amount
			row[ageing_bucket] += entry.principal_amount
			row["total"] += entry.interest_amount + entry.principal_amount

		data.append(row)

	return data


def get_ageing_bucket(as_on_date, payment_date):
	ageing_map = get_ageing_list()
	ageing_days = date_diff(as_on_date, payment_date)
	for key, value in ageing_map.items():
		start, end = key.split("-")
		if int(start) <= ageing_days <= int(end):
			return value


def get_future_interest_details(as_on_date, company):
	loans = frappe.db.get_all(
		"Loan",
		filters={
			"company": company,
			"docstatus": 1,
			"status": ("in", "Disbursed", "Partially Disbursed", "Active"),
		},
		pluck="name",
	)

	loan_repayment_schedules = frappe._dict(
		frappe.db.get_all(
			"Loan Repayment Schedule",
			filters={
				"loan": ("in", loans),
			},
			fields=["name", "loan"],
			as_list=1,
		)
	)

	repayment_schedules = [key for key, value in loan_repayment_schedules.items()]

	future_emis = frappe.db.get_all(
		"Repayment Schedule",
		filters={
			"parent": ("in", repayment_schedules),
			"payment_date": (">", as_on_date),
		},
		fields=["parent", "payment_date", "interest_amount", "principal_amount"],
	)

	future_details = {}
	for emi in future_emis:
		loan = loan_repayment_schedules.get(emi.parent)
		future_details.setdefault(loan, [])
		future_details[loan].append(emi)

	return future_details, loans


def get_overdue_details(as_on_date, company):
	loan_demand = frappe.qb.DocType("Loan Demand")
	query = (
		frappe.qb.from_(loan_demand)
		.select(
			loan_demand.loan,
			loan_demand.loan_product,
			loan_demand.demand_type,
			loan_demand.demand_subtype,
			loan_demand.demand_date,
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
