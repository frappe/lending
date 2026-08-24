import frappe

from lending.install import add_server_scripts

# Only this line is rewritten, so a site's own edits to the rule survive.
UNGUARDED_AGE_CONDITION = "if doc.age < 18:"
GUARDED_AGE_CONDITION = 'if doc.applicant_type == "Individual" and (doc.age or 0) < 18:'

# An earlier build of this release moved the cooling period and live loan limit rules out
# of applicant_exposure, and for a while ran them as workflow_methods with no script in
# front. Scripts a site wrote against either shape are repointed rather than replaced.
STALE_METHOD_PATHS = {
	"lending.loan_origination.applicant_exposure.": (
		"lending.loan_origination.doctype.loan_lead.applicant_exposure."
	),
}

# Rules that are Server Scripts again; the workflow_methods of the same name stay
# registered as the no-script path, so a site wired to either one keeps working.
LOAN_PRODUCT_DOCTYPE = "Loan Product"
PRODUCT_LIMIT_FIELD = "maximum_live_loans"

SCRIPT_BACKED_RULES = {
	"Validate Cooling Period": "Cooling period validation for Loan Lead",
	"Validate Live Loan Limit": "Live loan limit validation for Loan Lead",
}


def execute():
	# Unconditional on purpose: patches run before sync_fixtures, so the Workflow does not
	# exist yet on the migrate that first ships it, and the fixture's tasks link to these
	# scripts by name. add_server_scripts() is idempotent and never overwrites.
	add_server_scripts()
	guard_age_script()
	repoint_stale_method_paths()
	rewire_method_tasks_to_scripts()
	drop_product_live_loan_limit()


def drop_product_live_loan_limit():
	"""Drop the per-product live loan limit an earlier build of this release added.

	The limit is set in the Server Script that runs the rule, once for every product. A
	number left on a Loan Product used to beat that script, so a site that set it on one
	product silently stopped the script from governing there. Removing the field is what
	makes the script the only place the limit lives.
	"""
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
	"""Point scripts at the module the rules live in now, leaving the rest of them alone."""
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
	"""Swap a workflow_method task row for the Server Script that now fronts the rule.

	sync_fixtures rewrites the shipped Workflow Transition Tasks anyway; this covers the
	rows on any other document a site attached these rules to. The method stays registered,
	so nothing breaks if a site would rather keep the row as it is -- but leaving both the
	method row and a script row in place would run the rule twice, so the row is moved
	rather than added to.
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
