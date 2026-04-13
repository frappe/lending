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
			"width": 150,
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
	entries = []

	entries.extend(get_disbursement_entries(filters))
	entries.extend(get_repayment_entries(filters))
	entries.extend(get_demand_entries(filters))

	entries.sort(key=lambda x: (getdate(x["posting_date"]), x.get("_sort_order", 0)))

	if filters.get("group_by") == "Grouped":
		entries = group_entries(entries)

	# compute running balance
	balance = 0
	for entry in entries:
		balance += flt(entry.get("debit")) - flt(entry.get("credit"))
		entry["balance"] = balance
		entry["currency"] = default_currency
		entry.pop("_sort_order", None)

	return entries


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


def get_disbursement_entries(filters):
	conditions = get_filter_conditions(filters)
	conditions["disbursement_date"] = ["between", [filters["from_date"], filters["to_date"]]]

	if filters.get("loan"):
		conditions["against_loan"] = filters["loan"]

	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters=conditions,
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


def get_repayment_entries(filters):
	conditions = get_filter_conditions(filters)
	conditions["posting_date"] = ["between", [filters["from_date"], filters["to_date"]]]

	if filters.get("loan"):
		conditions["against_loan"] = filters["loan"]

	repayments = frappe.get_all(
		"Loan Repayment",
		filters=conditions,
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


def get_demand_entries(filters):
	conditions = {"docstatus": 1, "company": filters.get("company")}
	conditions["demand_date"] = ["between", [filters["from_date"], filters["to_date"]]]

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

	demands = frappe.get_all(
		"Loan Demand",
		filters=conditions,
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
