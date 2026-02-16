# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters: dict | None = None):
	columns = get_columns(filters)
	data = get_data(filters)

	return columns, data


def get_columns(filters) -> list[dict]:
	columns = [
		{
			"label": _("Date"),
			"fieldname": "date",
			"fieldtype": "Datetime",
		},
		{
			"label": _("Transaction Type"),
			"fieldname": "doctype",
			"fieldtype": "Data",
		},
		{
			"label": _("Loan Security"),
			"fieldname": "loan_security",
			"fieldtype": "Link",
			"options": "Loan Security",
		},
		{
			"label": _("Loan Security Type"),
			"fieldname": "loan_security_type",
			"fieldtype": "Link",
			"options": "Loan Security Type",
		},
		{
			"label": _("Loan"),
			"fieldname": "loan",
			"fieldtype": "Link",
			"options": "Loan",
		},
		{

			"label": _("Quantity"),
			"fieldname": "qty",
			"fieldtype": "Float",
		}
	]

	if filters.get("loan_security"):
		columns.append(
			{
				"label": _("Balance Quantity"),
				"fieldname": "balance_qty",
				"fieldtype": "Float",
			}
		)

	return columns


def get_data(filters) -> list[list]:
	loan = filters.get("loan")
	balance_qty = 0

	unpledges = frappe.db.sql(
		"""
			SELECT up.loan, "Loan Security Release" as doctype, u.loan_security, u.loan_security_type, u.qty, up.unpledge_time as date
			FROM `tabLoan Security Release` up, `tabUnpledge` u
			WHERE up.loan = %s
			AND u.parent = up.name
			AND up.status = 'Approved'
			GROUP BY u.loan_security
		""", (loan), as_dict=1
	)

	pledges = frappe.db.sql(
		"""
			SELECT lsa.loan, "Loan Security Assignment" as doctype, p.loan_security, p.loan_security_type, p.qty, lsa.pledge_time as date
			FROM `tabLoan Security Assignment` lsa, `tabPledge` p
			WHERE lsa.loan = %s
			AND p.parent = lsa.name
			AND lsa.status = 'Pledged'
			GROUP BY p.loan_security
		""", (loan), as_dict=1
	)

	result = pledges + unpledges

	if filters.get("loan_security"):
		for d in result:
			if d["doctype"] == "Loan Security Assignment":
				balance_qty += d["qty"]
			else:
				balance_qty -= d["qty"]

			d["balance_qty"] = balance_qty

	return sorted(result, key=lambda x: x.date)
