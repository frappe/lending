# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import date_diff, flt


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
			"fieldname": "ageing",
			"fieldtype": "Data",
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

	return columns


def get_ageing_map():
	ageing_map = {
		"0-0": "Overdue",
		"0-30": "0 to 1 Month",
		"30-60": "1 to 2 Months",
		"60-90": "2 to 3 Months",
		"90-180": "3 to 6 Months",
		"180-365": "6 to 12 Months",
		"365-730": "1 to 2 Years",
		"730-1095": "2 to 3 Years",
		"1095-1460": "3 to 4 Years",
		"1460-1825": "4 to 5 Years",
		"1825-100000": "5 Years and Above",
	}

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
		future_details = future_details_map.get(loan, {})

		parent_row = {
			"indent": 0,
			"loan": loan,
			"ageing": "",
			"loan_product": loan_product_map.get(loan),
			"accrued_principal": amounts.get("total_pending_principal", 0),
			"accrued_interest": amounts.get("total_pending_interest", 0),
			"penalty_amount": amounts.get("total_pending_penalty", 0),
			"total": 0,
		}

		total = (
			amounts.get("total_pending_principal", 0)
			+ amounts.get("total_pending_interest", 0)
			+ amounts.get("total_pending_penalty", 0)
		)

		child_data = [
			{
				"ageing": "Overdue",
				"accrued_principal": amounts.get("total_pending_principal", 0),
				"accrued_interest": amounts.get("total_pending_interest", 0),
				"penalty_amount": amounts.get("total_pending_penalty", 0),
				"indent": 1,
			}
		]
		for bucket, entry in future_details.items():
			child_row = {
				"accrued_principal": 0.0,
				"accrued_interest": 0.0,
				"penalty_amount": 0.0,
				"indent": 1,
			}
			child_row["accrued_interest"] += flt(entry.interest_amount)
			child_row["accrued_principal"] += flt(entry.principal_amount)
			child_row["penalty_amount"] += flt(entry.penalty_amount)
			child_row["ageing"] = bucket
			child_row["total"] = (
				child_row["accrued_principal"] + child_row["accrued_interest"] + child_row["penalty_amount"]
			)

			parent_row["accrued_interest"] += flt(entry.interest_amount)
			parent_row["accrued_principal"] += flt(entry.principal_amount)
			parent_row["penalty_amount"] += flt(entry.penalty_amount)
			parent_row["total"] += child_row["total"]

			child_data.append(child_row)

		data.append(parent_row)
		for child in child_data:
			data.append(child)

	return data


def get_ageing_bucket(as_on_date, payment_date):
	ageing_map = get_ageing_map()
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
		order_by="payment_date",
	)

	future_details = {}
	for emi in future_emis:
		loan = loan_repayment_schedules.get(emi.parent)
		future_details.setdefault(loan, frappe._dict())
		bucket_wise_details = future_details.get(loan)
		age_bucket = get_ageing_bucket(emi.payment_date, as_on_date)
		bucket_wise_details.setdefault(
			age_bucket,
			frappe._dict(
				{
					"interest_amount": 0.0,
					"principal_amount": 0.0,
				}
			),
		)

		bucket_wise_details[age_bucket]["interest_amount"] += emi.interest_amount
		bucket_wise_details[age_bucket]["principal_amount"] += emi.principal_amount

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
