# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate


class ProcessLoanRestructureLimit(Document):
	def on_submit(self):
		calculate_monthly_restructure_limit(posting_date=self.posting_date)


def calculate_monthly_restructure_limit(branch=None, posting_date=None):
	if not posting_date:
		posting_date = getdate()

	if branch:
		branches = [branch]
	else:
		branches = frappe.db.get_all("Branch", pluck="name")

	for company in frappe.get_all("Company", pluck="name"):
		for branch in branches:
			limit_details = frappe.db.get_value(
				"Branch", branch, ["loan_restructure_limit", "delinquent_limit"], as_dict=1
			)

			if not limit_details.loan_restructure_limit:
				loan_restructure_limit = frappe.db.get_value("Company", company, "loan_restructure_limit")
			else:
				loan_restructure_limit = limit_details.loan_restructure_limit

			if not limit_details.delinquent_limit:
				delinquent_limit = frappe.db.get_value("Company", company, "delinquent_limit")
			else:
				delinquent_limit = limit_details.delinquent_limit

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


def update_or_create_limit_log(
	company, branch, posting_date, limit_details, delinquent_limit_details
):
	existing_log = frappe.db.get_all(
		"Loan Restructure Limit Log",
		{"company": company, "branch": branch, "date": (">=", posting_date)},
		["name"],
		order_by="date desc",
		limit=1,
	)

	if existing_log:
		doc = frappe.get_doc("Loan Restructure Limit Log", existing_log[0].name)
		doc.update(limit_details)
		doc.update(delinquent_limit_details)
		doc.save()
	else:
		frappe.get_doc(
			{
				"doctype": "Loan Restructure Limit Log",
				"company": company,
				"branch": branch,
				"date": posting_date,
				"principal_outstanding": limit_details.principal_outstanding,
				"limit_percent": limit_details.limit_percent,
				"limit_amount": limit_details.limit_amount,
				"utilized_limit": limit_details.utilized_limit,
				"in_process_limit": limit_details.in_process_amount,
				"available_limit": flt(limit_details.limit_amount)
				- flt(limit_details.utilized_limit)
				- flt(limit_details.in_process_amount),
				"delinquent_principal_outstanding": delinquent_limit_details.delinquent_principal_outstanding,
				"delinquent_utilized_limit": delinquent_limit_details.delinquent_utilized_limit,
				"delinquent_limit_percent": delinquent_limit_details.delinquent_limit_percent,
				"delinquent_in_process_limit": delinquent_limit_details.delinquent_in_process_limit,
				"delinquent_limit_amount": delinquent_limit_details.delinquent_limit_amount,
				"delinquent_available_limit": flt(delinquent_limit_details.delinquent_limit_amount)
				- flt(delinquent_limit_details.delinquent_utilized_limit)
				- flt(delinquent_limit_details.delinquent_in_process_limit),
			}
		).insert()


def get_outstanding_pos(branch, company, delinquent=0):
	filters = {"branch": branch, "docstatus": 1, "status": "Disbursed", "company": company}

	if delinquent:
		filters.update({"days_past_due": (">=", 1)})

	pos = frappe.db.get_value(
		"Loan",
		filters,
		[
			"sum(total_payment) as total_payment",
			"sum(total_principal_paid) as total_principal_paid",
			"sum(total_interest_payable) as total_interest_payable",
		],
		as_dict=1,
	)

	return flt(pos.total_payment) - flt(pos.total_principal_paid) - flt(pos.total_interest_payable)


def get_utilized_limit(branch, company, delinquent=0):
	filters = {"branch": branch, "docstatus": 1, "company": company, "status": "Approved"}

	if delinquent:
		filters.update({"pre_restructure_dpd": (">=", 1)})

	utilized_limit = frappe.db.get_value(
		"Loan Restructure",
		filters,
		["sum(pending_principal_amount)"],
	)

	return flt(utilized_limit)


def get_in_process_limit(branch, company, delinquent=0):
	filters = {"branch": branch, "docstatus": 1, "company": company, "status": "Initiated"}

	if delinquent:
		filters.update({"pre_restructure_dpd": (">=", 1)})

	in_process_limit = frappe.db.get_value(
		"Loan Restructure", filters, ["sum(pending_principal_amount)"]
	)

	return flt(in_process_limit)
