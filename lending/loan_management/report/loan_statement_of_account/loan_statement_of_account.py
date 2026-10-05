# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	validate_filters(filters)
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data


def validate_filters(filters):
	if getdate(filters["from_date"]) > getdate(filters["to_date"]):
		frappe.throw(_("From Date cannot be after To Date"))


def get_columns(filters):
	default_currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
	is_grouped = filters.get("group_by") == "Grouped"

	columns = [
		{"label": _("Date"), "fieldtype": "Date", "fieldname": "posting_date", "width": 110},
		{
			"label": _("Transaction Type"),
			"fieldtype": "Data",
			"fieldname": "transaction_type",
			"width": 220,
		},
	]

	if not is_grouped:
		columns.append({
			"label": _("Transaction"),
			"fieldtype": "Dynamic Link",
			"fieldname": "transaction_name",
			"options": "transaction_doctype",
			"width": 200,
		})

	columns.extend([
		{
			"label": _("Loan"),
			"fieldtype": "Link",
			"fieldname": "loan",
			"options": "Loan",
			"width": 180,
		},
		{
			"label": _("Debit ({0})").format(default_currency),
			"fieldtype": "Currency",
			"fieldname": "debit",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Credit ({0})").format(default_currency),
			"fieldtype": "Currency",
			"fieldname": "credit",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Balance ({0})").format(default_currency),
			"fieldtype": "Currency",
			"fieldname": "balance",
			"options": "currency",
			"width": 140,
		},
		{"label": _("Remarks"), "fieldtype": "Data", "fieldname": "remarks", "width": 200},
		{
			"label": _("Currency"),
			"fieldtype": "Link",
			"fieldname": "currency",
			"options": "Currency",
			"width": 80,
			"hidden": 1,
		},
		{
			"label": _("Transaction DocType"),
			"fieldtype": "Data",
			"fieldname": "transaction_doctype",
			"width": 0,
			"hidden": 1,
		},
	])

	return columns


def get_data(filters):
	default_currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
	period = ["between", [filters["from_date"], filters["to_date"]]]
	entries = []

	entries.extend(get_disbursement_entries(filters, period))
	entries.extend(get_repayment_entries(filters, period))
	entries.extend(get_demand_entries(filters, period))

	entries.sort(key=lambda x: (getdate(x["posting_date"]), x.get("_sort_order", 0)))

	if filters.get("group_by") == "Grouped":
		entries = group_entries(entries)

	opening = get_opening_totals(filters)
	total = {"debit": 0, "credit": 0}

	balance = opening["debit"] - opening["credit"]
	for entry in entries:
		balance += flt(entry.get("debit")) - flt(entry.get("credit"))
		entry["balance"] = balance
		entry["currency"] = default_currency
		entry.pop("_sort_order", None)
		total["debit"] += flt(entry.get("debit"))
		total["credit"] += flt(entry.get("credit"))

	closing = {
		"debit": opening["debit"] + total["debit"],
		"credit": opening["credit"] + total["credit"],
	}

	return [
		get_summary_row(_("Opening"), opening, default_currency),
		*entries,
		get_summary_row(_("Total"), total, default_currency, show_balance=False),
		get_summary_row(_("Closing (Opening + Total)"), closing, default_currency),
	]


def get_summary_row(label, totals, currency, show_balance=True):
	return {
		"transaction_type": label,
		"debit": totals["debit"],
		"credit": totals["credit"],
		"balance": totals["debit"] - totals["credit"] if show_balance else None,
		"currency": currency,
	}


def get_opening_totals(filters):
	before_from_date = ["<", filters["from_date"]]

	debit = get_sum(
		"Loan Disbursement", get_disbursement_conditions(filters, before_from_date), "disbursed_amount"
	) + get_sum("Loan Demand", get_demand_conditions(filters, before_from_date), "demand_amount")
	credit = get_sum("Loan Repayment", get_repayment_conditions(filters, before_from_date), "amount_paid")

	return {"debit": debit, "credit": credit}


def get_sum(doctype, conditions, fieldname):
	result = frappe.get_all(doctype, filters=conditions, fields=[{"SUM": fieldname, "as": "total"}])
	return flt(result[0].total) if result else 0


def group_entries(entries):
	grouped = {}
	for entry in entries:
		key = (str(entry["posting_date"]), entry["transaction_type"], entry["loan"])
		if key not in grouped:
			grouped[key] = {
				"posting_date": entry["posting_date"],
				"transaction_type": entry["transaction_type"],
				"loan": entry["loan"],
				"debit": 0,
				"credit": 0,
				"remarks": "",
				"_sort_order": entry.get("_sort_order", 0),
			}
		grouped[key]["debit"] += flt(entry.get("debit"))
		grouped[key]["credit"] += flt(entry.get("credit"))

	result = list(grouped.values())
	result.sort(key=lambda x: (getdate(x["posting_date"]), x.get("_sort_order", 0)))
	return result


def get_filter_conditions(filters):
	conditions = {"company": filters.get("company"), "docstatus": 1}

	if filters.get("applicant"):
		conditions["applicant"] = filters.get("applicant")

	if filters.get("applicant_type"):
		conditions["applicant_type"] = filters.get("applicant_type")

	if filters.get("loan_product"):
		conditions["loan_product"] = filters.get("loan_product")

	return conditions


def get_disbursement_conditions(filters, date_condition):
	conditions = get_filter_conditions(filters)
	conditions["disbursement_date"] = date_condition

	if filters.get("loan"):
		conditions["against_loan"] = filters["loan"]

	return conditions


def get_disbursement_entries(filters, date_condition):
	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters=get_disbursement_conditions(filters, date_condition),
		fields=[
			"disbursement_date as posting_date",
			"name",
			"against_loan as loan",
			"disbursed_amount",
		],
	)

	entries = []
	for d in disbursements:
		entries.append(
			{
				"posting_date": d.posting_date,
				"transaction_type": _("Disbursement"),
				"transaction_doctype": "Loan Disbursement",
				"transaction_name": d.name,
				"loan": d.loan,
				"debit": flt(d.disbursed_amount),
				"credit": 0,
				"remarks": "",
				"_sort_order": 0,
			}
		)

	return entries


def get_repayment_conditions(filters, date_condition):
	conditions = get_filter_conditions(filters)
	conditions["posting_date"] = date_condition

	if filters.get("loan"):
		conditions["against_loan"] = filters["loan"]

	return conditions


def get_repayment_entries(filters, date_condition):
	repayments = frappe.get_all(
		"Loan Repayment",
		filters=get_repayment_conditions(filters, date_condition),
		fields=[
			"posting_date",
			"name",
			"against_loan as loan",
			"repayment_type",
			"principal_amount_paid",
			"total_interest_paid",
			"total_penalty_paid",
			"total_charges_paid",
			"amount_paid",
		],
	)

	entries = []
	for r in repayments:
		breakdown = []
		if flt(r.principal_amount_paid):
			breakdown.append(_("Principal: {0}").format(flt(r.principal_amount_paid, 2)))
		if flt(r.total_interest_paid):
			breakdown.append(_("Interest: {0}").format(flt(r.total_interest_paid, 2)))
		if flt(r.total_penalty_paid):
			breakdown.append(_("Penalty: {0}").format(flt(r.total_penalty_paid, 2)))
		if flt(r.total_charges_paid):
			breakdown.append(_("Charges: {0}").format(flt(r.total_charges_paid, 2)))

		remarks = r.repayment_type
		if breakdown:
			remarks += " (" + ", ".join(breakdown) + ")"

		entries.append(
			{
				"posting_date": r.posting_date,
				"transaction_type": r.repayment_type or _("Repayment"),
				"transaction_doctype": "Loan Repayment",
				"transaction_name": r.name,
				"loan": r.loan,
				"debit": 0,
				"credit": flt(r.amount_paid),
				"remarks": remarks,
				"_sort_order": 2,
			}
		)

	return entries


def get_demand_conditions(filters, date_condition):
	conditions = {"docstatus": 1, "company": filters.get("company")}
	conditions["demand_date"] = date_condition

	if filters.get("applicant"):
		conditions["applicant"] = filters.get("applicant")

	if filters.get("applicant_type"):
		conditions["applicant_type"] = filters.get("applicant_type")

	if filters.get("loan"):
		conditions["loan"] = filters["loan"]

	if filters.get("loan_product"):
		conditions["loan_product"] = filters.get("loan_product")

	# exclude principal EMI demands since disbursements already capture the debit
	conditions["demand_subtype"] = ["!=", "Principal"]

	return conditions


def get_demand_entries(filters, date_condition):
	demands = frappe.get_all(
		"Loan Demand",
		filters=get_demand_conditions(filters, date_condition),
		fields=[
			"demand_date as posting_date",
			"name",
			"loan",
			"demand_type",
			"demand_subtype",
			"demand_amount",
		],
	)

	entries = []
	for d in demands:
		demand_label = d.demand_type
		if d.demand_subtype:
			demand_label += " - " + d.demand_subtype

		entries.append(
			{
				"posting_date": d.posting_date,
				"transaction_type": demand_label,
				"transaction_doctype": "Loan Demand",
				"transaction_name": d.name,
				"loan": d.loan,
				"debit": flt(d.demand_amount),
				"credit": 0,
				"remarks": "",
				"_sort_order": 1,
			}
		)

	return entries
