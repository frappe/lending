# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, nowdate

from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	OPEN_STATUSES,
)

AGEING_BUCKETS = ((7, "0-7"), (15, "8-15"), (30, "16-30"))


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_data(filters):
	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	sale_map = get_sale_map()
	today = getdate(nowdate())

	data = []
	for shortfall in get_shortfalls(filters):
		days_open = date_diff(today, shortfall.creation)
		sale = sale_map.get(shortfall.name, {})
		data.append(
			{
				**shortfall,
				"opened_on": getdate(shortfall.creation),
				"days_open": days_open,
				"ageing": get_bucket(days_open),
				"days_past_cure_by": date_diff(today, shortfall.cure_by) if shortfall.cure_by else None,
				"loan_security_sale": sale.get("name"),
				"sale_status": sale.get("status"),
				"currency": currency,
			}
		)

	return data


def get_shortfalls(filters):
	shortfall = frappe.qb.DocType("Loan Security Shortfall")
	loan = frappe.qb.DocType("Loan")

	query = (
		frappe.qb.from_(shortfall)
		.left_join(loan)
		.on(shortfall.loan == loan.name)
		.select(
			shortfall.name.as_("loan_security_shortfall"),
			shortfall.name,
			shortfall.loan,
			shortfall.applicant,
			shortfall.status,
			shortfall.shortfall_amount,
			shortfall.shortfall_percentage.as_("current_ltv"),
			shortfall.creation,
			shortfall.notified_on,
			shortfall.cure_by,
			shortfall.missing_price,
		)
		.where(shortfall.status.isin([filters.status] if filters.status else list(OPEN_STATUSES)))
		# An applicant-wise shortfall has no loan, and so no company
		.where((loan.company == filters.company) | shortfall.loan.isnull())
		.orderby(shortfall.creation)
	)
	if filters.applicant:
		query = query.where(shortfall.applicant == filters.applicant)

	return query.run(as_dict=True)


def get_sale_map():
	return {
		row.loan_security_shortfall: row
		for row in frappe.get_all(
			"Loan Security Sale",
			filters={"loan_security_shortfall": ("is", "set"), "docstatus": ("<", 2)},
			fields=["name", "loan_security_shortfall", "status"],
			order_by="creation",
		)
	}


def get_bucket(days_open):
	for limit, label in AGEING_BUCKETS:
		if days_open <= limit:
			return label
	return "31+"


def get_columns():
	return [
		{
			"label": _("Shortfall"),
			"fieldname": "loan_security_shortfall",
			"fieldtype": "Link",
			"options": "Loan Security Shortfall",
			"width": 140,
		},
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 150},
		{"label": _("Applicant"), "fieldname": "applicant", "fieldtype": "Data", "width": 150},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
		{
			"label": _("Shortfall Amount"),
			"fieldname": "shortfall_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{"label": _("Current LTV"), "fieldname": "current_ltv", "fieldtype": "Percent", "width": 100},
		{"label": _("Prices Missing"), "fieldname": "missing_price", "fieldtype": "Check", "width": 110},
		{"label": _("Opened On"), "fieldname": "opened_on", "fieldtype": "Date", "width": 100},
		{"label": _("Days Open"), "fieldname": "days_open", "fieldtype": "Int", "width": 90},
		{"label": _("Ageing"), "fieldname": "ageing", "fieldtype": "Data", "width": 80},
		{"label": _("Notified On"), "fieldname": "notified_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Cure By"), "fieldname": "cure_by", "fieldtype": "Date", "width": 100},
		{"label": _("Days Past Cure By"), "fieldname": "days_past_cure_by", "fieldtype": "Int", "width": 120},
		{
			"label": _("Loan Security Sale"),
			"fieldname": "loan_security_sale",
			"fieldtype": "Link",
			"options": "Loan Security Sale",
			"width": 140,
		},
		{"label": _("Sale Status"), "fieldname": "sale_status", "fieldtype": "Data", "width": 110},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1,
		},
	]
