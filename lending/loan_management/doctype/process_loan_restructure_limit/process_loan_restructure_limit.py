# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, get_first_day, get_last_day, getdate

RUNNING_LOAN_STATUSES = ["Disbursed", "Partially Disbursed", "Active"]


class ProcessLoanRestructureLimit(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		posting_date: DF.Date | None
	# end: auto-generated types

	def on_submit(self):
		calculate_monthly_restructure_limit(posting_date=self.posting_date)


def calculate_monthly_restructure_limit(branch=None, posting_date=None):
	if not frappe.get_meta("Loan").has_field("branch"):
		return

	if not posting_date:
		posting_date = getdate()

	if branch:
		branches = [branch]
	else:
		branches = frappe.db.get_all("Branch", pluck="name")

	for company in frappe.get_all("Company", pluck="name"):
		for branch in branches:
			loan_restructure_limit = get_limit_percent("loan_restructure_limit", branch, company)
			delinquent_limit = get_limit_percent("delinquent_limit", branch, company)

			outstanding_pos = get_outstanding_pos(branch, company)
			delinquent_pos = get_outstanding_pos(branch, company, delinquent=1)

			utilized_limit = get_utilized_limit(branch, company)
			delinquent_utilized_limit = get_utilized_limit(branch, company, delinquent=1)

			in_process_amount = get_in_process_limit(branch, company)
			delinquent_in_process_limit = get_in_process_limit(branch, company, delinquent=1)

			limit_amount = outstanding_pos * flt(loan_restructure_limit) / 100
			delinquent_limit_amount = delinquent_pos * flt(delinquent_limit) / 100

			limit_details = frappe._dict(
				{
					"principal_outstanding": outstanding_pos,
					"limit_percent": loan_restructure_limit,
					"limit_amount": limit_amount,
					"utilized_limit": utilized_limit,
					"in_process_limit": in_process_amount,
					"available_limit": limit_amount - utilized_limit - in_process_amount,
				}
			)

			delinquent_limit_details = frappe._dict(
				{
					"delinquent_principal_outstanding": delinquent_pos,
					"delinquent_utilized_limit": delinquent_utilized_limit,
					"delinquent_limit_percent": delinquent_limit,
					"delinquent_in_process_limit": delinquent_in_process_limit,
					"delinquent_limit_amount": delinquent_limit_amount,
					"delinquent_available_limit": delinquent_limit_amount
					- delinquent_utilized_limit
					- delinquent_in_process_limit
					if delinquent_pos > 0
					else 0,
				}
			)

			update_or_create_limit_log(
				company, branch, posting_date, limit_details, delinquent_limit_details
			)


def get_limit_percent(fieldname, branch, company):
	for doctype, name in (("Branch", branch), ("Company", company)):
		if frappe.get_meta(doctype).has_field(fieldname):
			limit = frappe.db.get_value(doctype, name, fieldname)
			if limit:
				return limit


def update_or_create_limit_log(
	company, branch, posting_date, limit_details, delinquent_limit_details
):
	existing_log = frappe.db.get_all(
		"Loan Restructure Limit Log",
		{
			"company": company,
			"branch": branch,
			"date": ("between", [get_first_day(posting_date), get_last_day(posting_date)]),
		},
		["name"],
		order_by="date desc",
		limit=1,
	)

	if existing_log:
		doc = frappe.get_doc("Loan Restructure Limit Log", existing_log[0].name)
	else:
		doc = frappe.new_doc("Loan Restructure Limit Log")
		doc.update({"company": company, "branch": branch})

	doc.date = posting_date

	doc.update(limit_details)
	doc.update(delinquent_limit_details)
	doc.save()


def get_outstanding_pos(branch, company, delinquent=0):
	filters = {
		"branch": branch,
		"docstatus": 1,
		"status": ("in", RUNNING_LOAN_STATUSES),
		"company": company,
	}

	if delinquent:
		filters.update({"days_past_due": (">=", 1)})

	pos = frappe.db.get_value(
		"Loan",
		filters,
		[
			{"SUM": "total_payment", "as": "total_payment"},
			{"SUM": "total_principal_paid", "as": "total_principal_paid"},
			{"SUM": "total_interest_payable", "as": "total_interest_payable"},
			{"SUM": "debit_adjustment_amount", "as": "debit_adjustment_amount"},
			{"SUM": "credit_adjustment_amount", "as": "credit_adjustment_amount"},
		],
		as_dict=1,
	)

	return (
		flt(pos.total_payment)
		+ flt(pos.debit_adjustment_amount)
		- flt(pos.credit_adjustment_amount)
		- flt(pos.total_principal_paid)
		- flt(pos.total_interest_payable)
	)


def get_utilized_limit(branch, company, delinquent=0):
	filters = {
		"loan.branch": branch,
		"loan.status": ("in", RUNNING_LOAN_STATUSES),
		"docstatus": 1,
		"company": company,
		"status": "Approved",
	}

	if delinquent:
		filters.update({"pre_restructure_dpd": (">=", 1)})

	utilized_limit = frappe.db.get_value(
		"Loan Restructure",
		filters,
		[{"SUM": "pending_principal_amount"}],
	)

	return flt(utilized_limit)


def get_in_process_limit(branch, company, delinquent=0):
	filters = {"loan.branch": branch, "docstatus": 1, "company": company, "status": "Initiated"}

	if delinquent:
		filters.update({"pre_restructure_dpd": (">=", 1)})

	in_process_limit = frappe.db.get_value(
		"Loan Restructure", filters, [{"SUM": "pending_principal_amount"}]
	)

	return flt(in_process_limit)
