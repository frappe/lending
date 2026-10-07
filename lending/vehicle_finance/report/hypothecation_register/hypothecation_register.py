# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Loan Vehicle"), "fieldname": "name", "fieldtype": "Link", "options": "Loan Vehicle", "width": 160},
		{"label": _("Registration Number"), "fieldname": "registration_number", "fieldtype": "Data", "width": 150},
		{"label": _("Chassis Number"), "fieldname": "chassis_number", "fieldtype": "Data", "width": 170},
		{"label": _("Applicant"), "fieldname": "applicant_name", "fieldtype": "Data", "width": 160},
		{"label": _("Loan"), "fieldname": "current_loan", "fieldtype": "Link", "options": "Loan", "width": 160},
		{"label": _("Vehicle Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": _("Hypothecation Status"), "fieldname": "hypothecation_status", "fieldtype": "Data", "width": 160},
		{"label": _("Endorsed On"), "fieldname": "hypothecation_endorsed_on", "fieldtype": "Date", "width": 110},
		{"label": _("NOC Issued On"), "fieldname": "noc_issued_on", "fieldtype": "Date", "width": 110},
	]


def get_data(filters):
	conditions = {"hypothecation_status": ("!=", "Terminated"), "status": ("in", ("Financed", "Repossessed", "Released"))}
	if filters.get("company"):
		conditions["hypothecated_to"] = filters["company"]
	if filters.get("hypothecation_status"):
		conditions["hypothecation_status"] = filters["hypothecation_status"]

	return frappe.get_all(
		"Loan Vehicle",
		filters=conditions,
		fields=[
			"name",
			"registration_number",
			"chassis_number",
			"applicant_name",
			"current_loan",
			"status",
			"hypothecation_status",
			"hypothecation_endorsed_on",
			"noc_issued_on",
		],
		order_by="hypothecation_status asc, current_loan asc",
	)
