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
			"width": 200,
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
			"width": 200,
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
	if not filters.get("as_on_date"):
		frappe.throw(_("Please select As on Date."))

	params = {"as_on_date": filters["as_on_date"]}

	where_conditions = [
		"l.docstatus = 1",
		"lrs.docstatus = 1",
		"lrs.status = 'Active'",
		"l.status IN ('Disbursed', 'Partially Disbursed', 'Active')",
		"l.freeze_account = 0",
		"rs.payment_date >= %(as_on_date)s",
		"rs.demand_generated = 0",
	]

	for fl in ("company", "loan_product", "applicant", "loan"):
		if filters.get(fl):
			if fl == "loan":
				where_conditions.append("l.name = %({})s".format(fl))
			else:
				where_conditions.append("l.{0} = %({0})s".format(fl))
			params[fl] = filters[fl]

	where_clause = " AND ".join(where_conditions)

	query = """
		SELECT
			l.name AS loan,
			l.applicant,
			l.loan_product,
			rs.payment_date,
			rs.principal_amount,
			rs.interest_amount,
			(rs.principal_amount + rs.interest_amount) AS total_payment
		FROM `tabLoan` l
		JOIN `tabLoan Repayment Schedule` lrs ON lrs.loan = l.name
		JOIN `tabRepayment Schedule` rs
			ON rs.parent = lrs.name AND rs.parentfield = 'repayment_schedule'
		WHERE {where_clause}
		ORDER BY rs.payment_date
	""".format(
		where_clause=where_clause
	)

	results = frappe.db.sql(query, params, as_dict=True)
	return results
