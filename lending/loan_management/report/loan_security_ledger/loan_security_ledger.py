# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import functions as fn
from frappe.query_builder.custom import ConstantColumn


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
	applicant = filters.get("applicant")
	loan_security = filters.get("loan_security")

	if not (loan or applicant):
		frappe.throw(_("Please select at least Loan or Applicant to view the ledger"))

	balance_qty = 0

	unpldge_doctype = frappe.qb.DocType("Unpledge")
	loan_security_release_doctype = frappe.qb.DocType("Loan Security Release")

	pledge_doctype = frappe.qb.DocType("Pledge")
	loan_security_assignment_doctype = frappe.qb.DocType("Loan Security Assignment")

	unpledge_query = frappe.qb.from_(unpldge_doctype).inner_join(loan_security_release_doctype).on(
		unpldge_doctype.parent == loan_security_release_doctype.name
	).select(
		loan_security_release_doctype.loan, ConstantColumn("Loan Security Release").as_("doctype"), unpldge_doctype.loan_security, fn.Sum(unpldge_doctype.qty).as_("qty"), loan_security_release_doctype.unpledge_time.as_("date"), unpldge_doctype.loan_security_type
	).where(loan_security_release_doctype.docstatus == 1).where(loan_security_release_doctype.status == "Approved")

	pledge_query = frappe.qb.from_(pledge_doctype).inner_join(loan_security_assignment_doctype).on(
		pledge_doctype.parent == loan_security_assignment_doctype.name
	).select(
		loan_security_assignment_doctype.loan, ConstantColumn("Loan Security Assignment").as_("doctype"), pledge_doctype.loan_security, fn.Sum(pledge_doctype.qty).as_("qty"), loan_security_assignment_doctype.pledge_time.as_("date"), pledge_doctype.loan_security_type
	).where(loan_security_assignment_doctype.docstatus == 1).where(loan_security_assignment_doctype.status == "Pledged")

	if loan:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.loan == loan)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.loan == loan)

	if applicant:
		unpledge_query = unpledge_query.where(loan_security_release_doctype.applicant == applicant)
		pledge_query = pledge_query.where(loan_security_assignment_doctype.applicant == applicant)

	if loan_security:
		unpledge_query = unpledge_query.where(unpldge_doctype.loan_security == loan_security)
		pledge_query = pledge_query.where(pledge_doctype.loan_security == loan_security)

	if loan_security:
		unpledge_query = unpledge_query.where(unpldge_doctype.loan_security == loan_security)
		pledge_query = pledge_query.where(pledge_doctype.loan_security == loan_security)

	unpledges = unpledge_query.groupby(unpldge_doctype.loan_security).run(as_dict=True)
	pledges = pledge_query.groupby(pledge_doctype.loan_security).run(as_dict=True)

	result = pledges + unpledges

	if filters.get("loan_security"):
		for d in result:
			if d["doctype"] == "Loan Security Assignment":
				balance_qty += d["qty"]
			else:
				balance_qty -= d["qty"]

			d["balance_qty"] = balance_qty

	return sorted(result, key=lambda x: x.date)
