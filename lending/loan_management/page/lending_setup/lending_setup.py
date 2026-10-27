# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

COLLATERAL_KINDS = (
	{
		"label": "Mutual Funds",
		"description": "Units in a borrower's folio, priced daily from AMFI",
		"icon": "chart-line",
		"onboarding": "Mutual Fund Onboarding",
		"workspace": "Mutual Funds",
	},
	{"label": "Gold", "description": "Gold jewellery, valued by purity and weight", "icon": "gem"},
	{"label": "Shares", "description": "Listed shares held in a demat account", "icon": "chart-candlestick"},
	{"label": "Vehicles", "description": "A car or a two-wheeler, with its registration", "icon": "car"},
)


@frappe.whitelist()
def get_collateral_kinds() -> list[dict]:
	frappe.only_for(("System Manager", "Loan Manager"))
	return [get_kind(kind) for kind in COLLATERAL_KINDS]


def get_kind(kind: dict) -> dict:
	row = {"label": _(kind["label"]), "description": _(kind["description"]), "icon": kind["icon"]}
	onboarding = kind.get("onboarding")
	if not onboarding or not frappe.db.exists("Module Onboarding", onboarding):
		return row

	doc = frappe.get_doc("Module Onboarding", onboarding)
	steps = [frappe.get_doc("Onboarding Step", s.step) for s in doc.steps if not s.is_optional]
	row.update(
		workspace=kind["workspace"],
		total=len(steps),
		done=sum(1 for step in steps if step.is_complete or step.is_work_done()),
	)
	return row
