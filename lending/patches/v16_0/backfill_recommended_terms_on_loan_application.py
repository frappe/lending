import frappe

from lending.loan_origination.decisioning import RECOMMENDED_TERM_FIELDS


def execute():
	if not all(frappe.db.has_column("Loan Application", field) for field in RECOMMENDED_TERM_FIELDS):
		return

	applications = frappe.get_all(
		"Loan Application", filters={"decision": ("is", "set")}, fields=["name", "decision"]
	)

	if not applications:
		return

	terms_by_decision = {
		decision.name: decision
		for decision in frappe.get_all(
			"Loan Decision",
			filters={"name": ("in", [a.decision for a in applications]), "docstatus": 1},
			fields=["name", *RECOMMENDED_TERM_FIELDS],
		)
	}

	for application in applications:
		terms = terms_by_decision.get(application.decision)

		if not terms:
			continue

		frappe.db.set_value(
			"Loan Application",
			application.name,
			{field: terms.get(field) or 0 for field in RECOMMENDED_TERM_FIELDS},
			update_modified=False,
		)
