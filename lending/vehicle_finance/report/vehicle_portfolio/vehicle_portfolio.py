# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	get_pending_principal_amount,
)

GROUP_BY_FIELDS = {
	"Make": "make",
	"Vehicle Model": "vehicle_model",
	"Segment": "segment",
	"Asset Condition": "asset_condition",
	"Manufacturing Year": "manufacturing_year",
}
LOAN_FIELDS = [
	"name",
	"status",
	"total_payment",
	"debit_adjustment_amount",
	"credit_adjustment_amount",
	"refund_amount",
	"total_principal_paid",
	"loan_amount",
	"total_interest_payable",
	"written_off_amount",
	"disbursed_amount",
	"repayment_schedule_type",
]


def execute(filters=None):
	filters = filters or {}
	group_by = GROUP_BY_FIELDS.get(filters.get("group_by") or "Make")
	return get_columns(filters), get_data(filters, group_by)


def get_columns(filters):
	return [
		{"label": _(filters.get("group_by") or "Make"), "fieldname": "group", "fieldtype": "Data", "width": 220},
		{"label": _("Vehicles"), "fieldname": "vehicles", "fieldtype": "Int", "width": 100},
		{"label": _("Asset Value"), "fieldname": "asset_value", "fieldtype": "Currency", "width": 160},
		{"label": _("Outstanding Principal"), "fieldname": "outstanding_principal", "fieldtype": "Currency", "width": 180},
		{"label": _("Share of Outstanding (%)"), "fieldname": "share", "fieldtype": "Percent", "width": 160},
	]


def get_data(filters, group_by):
	vehicles = frappe.get_list(
		"Loan Vehicle",
		filters={"status": "Financed", **({"hypothecated_to": filters["company"]} if filters.get("company") else {})},
		fields=["name", "current_loan", "asset_value", group_by],
	)
	loans = {
		loan.name: loan
		for loan in frappe.get_list(
			"Loan", filters={"name": ("in", list({v.current_loan for v in vehicles}))}, fields=LOAN_FIELDS
		)
	}
	vehicles_per_loan = {}
	for vehicle in vehicles:
		vehicles_per_loan[vehicle.current_loan] = vehicles_per_loan.get(vehicle.current_loan, 0) + 1

	groups = {}
	for vehicle in vehicles:
		key = vehicle.get(group_by) or _("Not Set")
		group = groups.setdefault(key, frappe._dict(group=key, vehicles=0, asset_value=0, outstanding_principal=0))
		group.vehicles += 1
		group.asset_value += flt(vehicle.asset_value)
		loan = loans.get(vehicle.current_loan)
		if loan:
			group.outstanding_principal += get_pending_principal_amount(loan) / vehicles_per_loan[vehicle.current_loan]

	total = sum(group.outstanding_principal for group in groups.values())
	for group in groups.values():
		group.share = flt(group.outstanding_principal / total * 100, 2) if total else 0

	return sorted(groups.values(), key=lambda group: group.outstanding_principal, reverse=True)
