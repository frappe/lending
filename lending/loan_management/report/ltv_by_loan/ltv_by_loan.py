# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	DRAWN_SECURED_LOANS,
	OPEN_STATUSES,
	OUTSTANDING_FIELDS,
	CollateralValuation,
	get_current_ltv,
	get_outstanding_amount,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_data(filters):
	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	shortfall_map = get_open_shortfall_map()
	valuation = CollateralValuation()

	data = []
	for loan in get_loans(filters):
		outstanding_amount = get_outstanding_amount(loan)
		collateral = valuation.value_loan(loan.name)
		value = collateral.security_value
		shortfall = shortfall_map.get(loan.name, {})

		if filters.only_above_ltv and flt(outstanding_amount - collateral.allowed_amount, 2) <= 0:
			continue

		data.append(
			{
				"loan": loan.name,
				"applicant": loan.applicant,
				"loan_product": loan.loan_product,
				"outstanding_amount": outstanding_amount,
				"security_value": value,
				"allowed_amount": collateral.allowed_amount,
				"headroom": collateral.allowed_amount - outstanding_amount,
				"current_ltv": get_current_ltv(outstanding_amount, value),
				"ltv_limit": get_current_ltv(collateral.allowed_amount, value),
				"sell_ltv": get_current_ltv(collateral.sell_amount, value) if collateral.has_sell_level else None,
				"missing_price": collateral.missing_price,
				"loan_security_shortfall": shortfall.get("name"),
				"shortfall_status": shortfall.get("status"),
				"currency": currency,
			}
		)

	return sorted(data, key=lambda row: flt(row["current_ltv"]), reverse=True)


def get_loans(filters):
	loan_filters = dict(DRAWN_SECURED_LOANS, company=filters.company)
	for field in ("applicant", "loan_product"):
		if filters.get(field):
			loan_filters[field] = filters.get(field)

	# get_list, so that a reader's user permissions (for example, one company) apply
	return frappe.get_list(
		"Loan", filters=loan_filters, fields=[*OUTSTANDING_FIELDS, "applicant", "loan_product"]
	)


def get_open_shortfall_map():
	return {
		row.loan: row
		for row in frappe.get_all(
			"Loan Security Shortfall",
			filters={"status": ("in", OPEN_STATUSES), "loan": ("is", "set")},
			fields=["name", "loan", "status"],
		)
	}


def get_columns():
	return [
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 160},
		{"label": _("Applicant"), "fieldname": "applicant", "fieldtype": "Data", "width": 160},
		{
			"label": _("Loan Product"),
			"fieldname": "loan_product",
			"fieldtype": "Link",
			"options": "Loan Product",
			"width": 140,
		},
		{
			"label": _("Outstanding"),
			"fieldname": "outstanding_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Collateral Value"),
			"fieldname": "security_value",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Allowed Amount"),
			"fieldname": "allowed_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Headroom"),
			"fieldname": "headroom",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{"label": _("Current LTV"), "fieldname": "current_ltv", "fieldtype": "Percent", "width": 110},
		{"label": _("LTV Limit"), "fieldname": "ltv_limit", "fieldtype": "Percent", "width": 100},
		{"label": _("Sell LTV"), "fieldname": "sell_ltv", "fieldtype": "Percent", "width": 100},
		{"label": _("Prices Missing"), "fieldname": "missing_price", "fieldtype": "Check", "width": 110},
		{
			"label": _("Open Shortfall"),
			"fieldname": "loan_security_shortfall",
			"fieldtype": "Link",
			"options": "Loan Security Shortfall",
			"width": 140,
		},
		{"label": _("Shortfall Status"), "fieldname": "shortfall_status", "fieldtype": "Data", "width": 120},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1,
		},
	]
