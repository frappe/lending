# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt

import erpnext


def execute(filters=None):
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data


def get_columns(filters):
	columns = [
		{
			"label": _("Applicant Type"),
			"fieldname": "applicant_type",
			"options": "DocType",
			"width": 100,
		},
		{
			"label": _("Applicant Name"),
			"fieldname": "applicant_name",
			"fieldtype": "Dynamic Link",
			"options": "applicant_type",
			"width": 150,
		},
		{
			"label": _("Loan Security"),
			"fieldname": "loan_security",
			"fieldtype": "Link",
			"options": "Loan Security",
			"width": 160,
		},
		{
			"label": _("Loan Security Code"),
			"fieldname": "loan_security_code",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Loan Security Name"),
			"fieldname": "loan_security_name",
			"fieldtype": "Data",
			"width": 150,
		},
		{"label": _("Haircut"), "fieldname": "haircut", "fieldtype": "Percent", "width": 100},
		{
			"label": _("Loan Security Type"),
			"fieldname": "loan_security_type",
			"fieldtype": "Link",
			"options": "Loan Security Type",
			"width": 120,
		},
		{"label": _("Disabled"), "fieldname": "disabled", "fieldtype": "Check", "width": 80},
		{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 100},
		{
			"label": _("Latest Price"),
			"fieldname": "latest_price",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 100,
		},
		{
			"label": _("Price Valid Upto"),
			"fieldname": "price_valid_upto",
			"fieldtype": "Datetime",
			"width": 100,
		},
		{
			"label": _("Current Value"),
			"fieldname": "current_value",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 100,
		},
		{
			"label": _("% Of Applicant Portfolio"),
			"fieldname": "portfolio_percent",
			"fieldtype": "Percentage",
			"width": 100,
		},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Currency",
			"options": "Currency",
			"hidden": 1,
			"width": 100,
		},
	]

	return columns


def get_data(filters):
	data = []
	loan_security_details = get_loan_security_details()
	pledge_values, total_value_map, applicant_type_map = get_applicant_wise_total_loan_security_qty(
		filters, loan_security_details
	)

	currency = erpnext.get_company_currency(filters.get("company"))

	for key, qty in pledge_values.items():
		if qty:
			row = {}
			current_value = flt(qty * loan_security_details.get(key[1], {}).get("latest_price", 0))
			valid_upto = loan_security_details.get(key[1], {}).get("valid_upto")

			row.update(loan_security_details.get(key[1]))
			row.update(
				{
					"applicant_type": applicant_type_map.get(key[0]),
					"applicant_name": key[0],
					"total_qty": qty,
					"current_value": current_value,
					"price_valid_upto": valid_upto,
					"portfolio_percent": flt(current_value * 100 / total_value_map.get(key[0]), 2)
					if total_value_map.get(key[0])
					else 0.0,
					"currency": currency,
				}
			)

			data.append(row)

	return data


def get_loan_security_details():
	security_detail_map = {}
	loan_security_price_map = {}
	lsp_validity_map = {}

	loan_security_prices = frappe.db.sql(
		"""
		SELECT loan_security, loan_security_price, valid_upto
		FROM `tabLoan Security Price` t1
		WHERE valid_from >= (SELECT MAX(valid_from) FROM `tabLoan Security Price` t2
		WHERE t1.loan_security = t2.loan_security)
	""",
		as_dict=1,
	)

	for security in loan_security_prices:
		loan_security_price_map.setdefault(security.loan_security, security.loan_security_price)
		lsp_validity_map.setdefault(security.loan_security, security.valid_upto)

	loan_security_details = frappe.get_all(
		"Loan Security",
		fields=[
			"name as loan_security",
			"loan_security_code",
			"loan_security_name",
			"haircut",
			"loan_security_type",
			"disabled",
		],
	)

	for security in loan_security_details:
		security.update(
			{
				"latest_price": flt(loan_security_price_map.get(security.loan_security)),
				"valid_upto": lsp_validity_map.get(security.loan_security),
			}
		)

		security_detail_map.setdefault(security.loan_security, security)

	return security_detail_map


def get_applicant_wise_total_loan_security_qty(filters, loan_security_details):
	current_pledges = {}
	total_value_map = {}
	applicant_type_map = {}
	applicant_wise_unpledges = {}

	company = filters.get("company")

	lsr = frappe.qb.DocType("Loan Security Release")
	unpledge = frappe.qb.DocType("Unpledge")
	unpledge_query = (
		frappe.qb.from_(lsr)
		.inner_join(unpledge)
		.on(unpledge.parent == lsr.name)
		.select(lsr.applicant, unpledge.loan_security, Sum(unpledge.qty).as_("qty"))
		.where(lsr.status == "Approved")
		.groupby(lsr.applicant, unpledge.loan_security)
	)
	if company:
		unpledge_query = unpledge_query.where(lsr.company == company)

	unpledges = unpledge_query.run(as_dict=1)

	for row in unpledges:
		applicant_wise_unpledges.setdefault((row.applicant, row.loan_security), row.qty)

	lsa = frappe.qb.DocType("Loan Security Assignment")
	pledge = frappe.qb.DocType("Pledge")
	pledge_query = (
		frappe.qb.from_(lsa)
		.inner_join(pledge)
		.on(pledge.parent == lsa.name)
		.select(lsa.applicant_type, lsa.applicant, pledge.loan_security, Sum(pledge.qty).as_("qty"))
		.where(lsa.status == "Pledged")
		.groupby(lsa.applicant, pledge.loan_security)
	)
	if company:
		pledge_query = pledge_query.where(lsa.company == company)

	pledges = pledge_query.run(as_dict=1)

	for security in pledges:
		current_pledges.setdefault((security.applicant, security.loan_security), security.qty)
		total_value_map.setdefault(security.applicant, 0.0)
		applicant_type_map.setdefault(security.applicant, security.applicant_type)

		current_pledges[(security.applicant, security.loan_security)] -= applicant_wise_unpledges.get(
			(security.applicant, security.loan_security), 0.0
		)

		total_value_map[security.applicant] += current_pledges.get(
			(security.applicant, security.loan_security)
		) * loan_security_details.get(security.loan_security, {}).get("latest_price", 0)

	return current_pledges, total_value_map, applicant_type_map
