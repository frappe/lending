# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_months, flt

from lending.vehicle_finance.loan_hooks import get_vehicle_age_in_years


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Loan Vehicle"), "fieldname": "name", "fieldtype": "Link", "options": "Loan Vehicle", "width": 160},
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 160},
		{"label": _("Asset Condition"), "fieldname": "asset_condition", "fieldtype": "Data", "width": 120},
		{"label": _("Segment"), "fieldname": "segment", "fieldtype": "Data", "width": 90},
		{"label": _("Manufactured"), "fieldname": "manufactured", "fieldtype": "Data", "width": 120},
		{"label": _("Age at Sanction (Years)"), "fieldname": "age_at_sanction", "fieldtype": "Float", "precision": 1, "width": 170},
		{"label": _("Age at Maturity (Years)"), "fieldname": "age_at_maturity", "fieldtype": "Float", "precision": 1, "width": 170},
	]


def get_data(filters):
	conditions = {"status": "Financed"}
	if filters.get("company"):
		conditions["hypothecated_to"] = filters["company"]

	vehicles = frappe.get_all(
		"Loan Vehicle",
		filters=conditions,
		fields=["name", "current_loan", "asset_condition", "segment", "manufacturing_month", "manufacturing_year"],
	)
	loans = {
		loan.name: loan
		for loan in frappe.get_all(
			"Loan",
			filters={"name": ("in", {v.current_loan for v in vehicles})},
			fields=["name", "posting_date", "repayment_periods"],
		)
	}

	rows = []
	for vehicle in vehicles:
		loan = loans.get(vehicle.current_loan)
		if not loan:
			continue

		rows.append(
			{
				"name": vehicle.name,
				"loan": loan.name,
				"asset_condition": vehicle.asset_condition,
				"segment": vehicle.segment,
				"manufactured": f"{vehicle.manufacturing_month} {vehicle.manufacturing_year}",
				"age_at_sanction": flt(get_vehicle_age_in_years(vehicle, loan.posting_date), 1),
				"age_at_maturity": flt(
					get_vehicle_age_in_years(vehicle, add_months(loan.posting_date, loan.repayment_periods or 0)), 1
				),
			}
		)

	return sorted(rows, key=lambda row: row["age_at_maturity"], reverse=True)
