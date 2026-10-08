# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, getdate

BUCKETS = ((30, "0-30"), (60, "31-60"), (90, "61-90"))


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Document"), "fieldname": "name", "fieldtype": "Link", "options": "Post Disbursal Document", "width": 160},
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 160},
		{"label": _("Applicant"), "fieldname": "applicant", "fieldtype": "Data", "width": 160},
		{"label": _("Loan Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Loan Vehicle", "width": 160},
		{"label": _("Document Type"), "fieldname": "document_type", "fieldtype": "Link", "options": "Loan Document Type", "width": 140},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 110},
		{"label": _("Bucket"), "fieldname": "bucket", "fieldtype": "Data", "width": 90},
	]


def get_data(filters):
	conditions = {"status": ("in", ("Pending", "Overdue"))}
	for fieldname in ("company", "loan", "document_type"):
		if filters.get(fieldname):
			conditions[fieldname] = filters.get(fieldname)

	as_on_date = getdate(filters.get("as_on_date"))
	rows = frappe.get_list(
		"Post Disbursal Document",
		filters=conditions,
		fields=["name", "loan", "applicant", "vehicle", "document_type", "status", "due_date"],
		order_by="due_date asc",
	)

	for row in rows:
		row.days_overdue = max(date_diff(as_on_date, row.due_date), 0)
		row.bucket = get_bucket(row.days_overdue) if row.days_overdue else _("Not Due")

	return rows


def get_bucket(days):
	for limit, label in BUCKETS:
		if days <= limit:
			return label
	return "90+"
