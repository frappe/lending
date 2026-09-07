import frappe

from lending.install import GUARDED_AGE_CONDITION, add_server_scripts

UNGUARDED_AGE_CONDITION = "if doc.age < 18:"

# An earlier build of this release moved these rules into the Loan Lead module.
STALE_METHOD_PATHS = {
	"lending.loan_origination.applicant_exposure.": (
		"lending.loan_origination.doctype.loan_lead.applicant_exposure."
	),
}

LOAN_PRODUCT_DOCTYPE = "Loan Product"
PRODUCT_LIMIT_FIELD = "maximum_live_loans"

SCRIPT_BACKED_RULES = {
	"Validate Cooling Period": "Cooling period validation for Loan Lead",
	"Validate Live Loan Limit": "Live loan limit validation for Loan Lead",
}


def execute():
	# Unconditional: patches run before sync_fixtures, whose tasks link these scripts by
	# name. add_server_scripts() is idempotent and never overwrites.
	add_server_scripts()
	guard_age_script()
	repoint_stale_method_paths()
	rewire_method_tasks_to_scripts()
	drop_product_live_loan_limit()


def drop_product_live_loan_limit():
	"""Drop the per-product limit an earlier build added; it used to override the script."""
	if not frappe.db.has_column(LOAN_PRODUCT_DOCTYPE, PRODUCT_LIMIT_FIELD):
		return

	frappe.db.delete(
		"Property Setter", {"doc_type": LOAN_PRODUCT_DOCTYPE, "field_name": PRODUCT_LIMIT_FIELD}
	)
	frappe.db.sql_ddl(
		f"ALTER TABLE `tab{LOAN_PRODUCT_DOCTYPE}` DROP COLUMN `{PRODUCT_LIMIT_FIELD}`"
	)
	frappe.clear_cache(doctype=LOAN_PRODUCT_DOCTYPE)


def guard_age_script():
	name = "Age validation for Loan Lead"
	script = frappe.db.get_value("Server Script", name, "script")

	if not script or UNGUARDED_AGE_CONDITION not in script:
		return

	frappe.db.set_value(
		"Server Script",
		name,
		"script",
		script.replace(UNGUARDED_AGE_CONDITION, GUARDED_AGE_CONDITION),
	)


def repoint_stale_method_paths():
	for name, script in frappe.get_all(
		"Server Script",
		filters={"script_type": "Workflow Task"},
		fields=["name", "script"],
		as_list=True,
	):
		if not script:
			continue

		updated = script
		for stale, current in STALE_METHOD_PATHS.items():
			updated = updated.replace(stale, current)

		if updated != script:
			frappe.db.set_value("Server Script", name, "script", updated)


def rewire_method_tasks_to_scripts():
	"""Covers rows on documents outside the shipped fixture. The row is moved, not added
	to: a method row and a script row for the same rule would run it twice.
	"""
	for task, script in SCRIPT_BACKED_RULES.items():
		if not frappe.db.exists("Server Script", script):
			continue

		for name in frappe.get_all(
			"Workflow Transition Task", filters={"task": task}, pluck="name"
		):
			frappe.db.set_value(
				"Workflow Transition Task",
				name,
				{"task": "Server Script", "link": script},
				update_modified=False,
			)
