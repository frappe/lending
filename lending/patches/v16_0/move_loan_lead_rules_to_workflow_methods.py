import frappe

from lending.install import add_server_scripts

# Only this line is rewritten, so a site's own edits to the rule survive.
UNGUARDED_AGE_CONDITION = "if doc.age < 18:"
GUARDED_AGE_CONDITION = 'if doc.applicant_type == "Individual" and (doc.age or 0) < 18:'

# Server Scripts an earlier build of this release created; they are workflow_methods now.
SUPERSEDED_SERVER_SCRIPTS = (
	"Cooling period validation for Loan Lead",
	"Live loan limit validation for Loan Lead",
)


def execute():
	# Unconditional on purpose: patches run before sync_fixtures, so the Workflow does not
	# exist yet on the migrate that first ships it. add_server_scripts() is idempotent.
	add_server_scripts()
	guard_age_script()
	drop_superseded_server_scripts()


def guard_age_script():
	name = "Age validation for Loan Lead"
	script = frappe.db.get_value("Server Script", name, "script")

	if not script or UNGUARDED_AGE_CONDITION not in script:
		return

	frappe.db.set_value(
		"Server Script", name, "script", script.replace(UNGUARDED_AGE_CONDITION, GUARDED_AGE_CONDITION)
	)


def drop_superseded_server_scripts():
	# The rows go first, or deleting the script trips its own link check.
	frappe.db.delete(
		"Workflow Transition Task",
		{"task": "Server Script", "link": ["in", SUPERSEDED_SERVER_SCRIPTS]},
	)

	for name in SUPERSEDED_SERVER_SCRIPTS:
		frappe.delete_doc(
			"Server Script", name, force=True, ignore_missing=True, delete_permanently=True
		)
