import frappe


def execute():
	# Lending Settings already exists, so the new field's default never reaches it.
	# get_single_value casts a missing value to 0, so look for the row itself.
	singles = frappe.qb.DocType("Singles")
	saved = (
		frappe.qb.from_(singles)
		.select(singles.value)
		.where(singles.doctype == "Lending Settings")
		.where(singles.field == "gold_credit_assessment_above")
		.run()
	)
	if not saved:
		frappe.db.set_single_value("Lending Settings", "gold_credit_assessment_above", 250000)
