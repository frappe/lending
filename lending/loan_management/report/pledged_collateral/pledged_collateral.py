# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, get_datetime

from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	get_ltv_ratio_map,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_data(filters):
	"""One row per security per loan, at the quantity still pledged after releases and sales."""
	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	security_map = get_security_map()
	price_map = get_current_prices()
	ltv_ratio_map = get_ltv_ratio_map()

	data = []
	for loan in get_loans(filters):
		for security, qty in get_pledged_security_qty(loan=loan.name).items():
			details = security_map.get(security, {})
			if flt(qty) <= 0 or (
				filters.loan_security_type and details.get("loan_security_type") != filters.loan_security_type
			):
				continue

			price = price_map.get(security, {})
			value = flt(qty) * flt(price.get("loan_security_price"))
			ltv = flt(ltv_ratio_map.get(security))
			data.append(
				{
					"loan": loan.name,
					"applicant": loan.applicant,
					"loan_security": security,
					"loan_security_name": details.get("loan_security_name"),
					"loan_security_type": details.get("loan_security_type"),
					"qty": qty,
					"price": price.get("loan_security_price"),
					"price_valid_upto": price.get("valid_upto"),
					"value": value,
					"ltv": ltv,
					"allowed_amount": value * ltv / 100,
					"currency": currency,
				}
			)

	return data


def get_loans(filters):
	loan_filters = {"docstatus": 1, "is_secured_loan": 1, "company": filters.company, "status": ("!=", "Closed")}
	if filters.loan:
		loan_filters["name"] = filters.loan
	if filters.applicant:
		loan_filters["applicant"] = filters.applicant

	return frappe.get_all("Loan", filters=loan_filters, fields=["name", "applicant"])


def get_security_map():
	return {
		row.name: row
		for row in frappe.get_all(
			"Loan Security", fields=["name", "loan_security_name", "loan_security_type"]
		)
	}


def get_current_prices():
	now = get_datetime()
	return {
		row.loan_security: row
		for row in frappe.get_all(
			"Loan Security Price",
			filters={"valid_from": ("<=", now), "valid_upto": (">=", now)},
			fields=["loan_security", "loan_security_price", "valid_upto"],
		)
	}


def get_columns():
	return [
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 160},
		{"label": _("Applicant"), "fieldname": "applicant", "fieldtype": "Data", "width": 160},
		{
			"label": _("Loan Security"),
			"fieldname": "loan_security",
			"fieldtype": "Link",
			"options": "Loan Security",
			"width": 140,
		},
		{"label": _("Security Name"), "fieldname": "loan_security_name", "fieldtype": "Data", "width": 150},
		{
			"label": _("Security Type"),
			"fieldname": "loan_security_type",
			"fieldtype": "Link",
			"options": "Loan Security Type",
			"width": 120,
		},
		{"label": _("Pledged Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 110},
		{
			"label": _("Current Price"),
			"fieldname": "price",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{"label": _("Price Valid Upto"), "fieldname": "price_valid_upto", "fieldtype": "Datetime", "width": 160},
		{
			"label": _("Value"),
			"fieldname": "value",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{"label": _("LTV"), "fieldname": "ltv", "fieldtype": "Percent", "width": 80},
		{
			"label": _("Allowed Amount"),
			"fieldname": "allowed_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1,
		},
	]
