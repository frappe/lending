app_name = "lending"
app_title = "Lending"
app_publisher = "Frappe Technologies Pvt. Ltd."
app_description = "Open Source Lending software"
app_email = "contact@frappe.io"
app_license = "GNU General Public License (v3)"
# studio serves the borrower portal. Every /borrower-portal route is a Studio Page: the
# doctype, the route, the renderer and the app bundle all come from that app, so without
# it the portal is silently absent rather than broken in a way that points at the cause.
# Declaring it here installs it alongside lending and stops it being uninstalled from
# under the portal.
required_apps = ["erpnext", "frappe/studio"]
app_logo_url = "/assets/lending/images/frappe-lending-logo.svg"

add_to_apps_screen = [
	{
		"name": "lending",
		"logo": "/assets/lending/images/frappe-lending-logo.svg",
		"title": "Lending",
		"route": "/app/lending",
		"has_permission": "lending.utils.check_app_permission",
	}
]

audit_trail_doctypes = [
	# doctypes that make GL entries require Audit Trail to be maintained
	# as per the laws applicable to Companies in India
	"Loan Balance Adjustment",
	"Loan Disbursement",
	"Loan Interest Accrual",
	"Loan Refund",
	"Loan Repayment",
	"Loan Write Off",
]

voucher_subtypes = "lending.loan_management.doctype.loan.loan.get_voucher_subtypes"

before_tests = "lending.tests.test_utils.before_tests"

ignore_translatable_strings_from = ["frappe", "erpnext"]
export_python_type_annotations = True
require_type_annotated_api_methods = True

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/lending/css/lending.css"
app_include_js = "lending.bundle.js"

# fixtures
fixtures = [
	{"dt": "Role", "filters": [["role_name", "like", "Loan %"]]},
	{"dt": "Workflow", "filters": [["name", "in", ("Loan Application Workflow", "Loan Lead Workflow")]]},
	{"dt": "Workflow State", "filters": [["name", "not in", ("Rejected", "Approved", "Pending")]]},
	{
		"dt": "Workflow Action Master",
		"filters": [["name", "not in", ("Reject", "Approve", "Review")]],
	},
	{
		"dt": "Workflow Transition Tasks",
		"filters": [["name", "in", ("Loan Lead Basic Rules",)]],
	},
	# The layouts behind the borrower portal's two downloads. Named rather than
	# filtered by doctype, so a site's own Print Formats on Loan are left alone.
	{
		"dt": "Print Format",
		"filters": [["name", "in", ("Loan Statement of Account", "Loan Interest Certificate")]],
	},
]


# include js, css files in header of web template
# web_include_css = "/assets/lending/css/lending.css"
# web_include_js = "/assets/lending/js/lending.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "lending/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Portal menu
# -----------

# The borrower portal's pages, as rows of frappe's own portal menu -- Portal Settings,
# the portal_menu_items hook and website.utils.get_portal_sidebar_items.
#
# The Studio sidebar does not read these. A Studio Component has no data source of its
# own and its tree is fixed at build time, so the rows it draws are declared in
# portal.studio_build.shell instead, and a page added is a line in both places.
#
# What still reads them is portal.core.nav_items(), and through it portal.search: a
# borrower searching for "statement" should find the page as well as the entries on it.
# The routes are in the /borrower-portal/ form the rest of the data layer speaks --
# loan_url and application_url too -- because nav_items keeps only the rows under
# core.PORTAL_ROUTE_PREFIX. The Studio app strips the prefix as it routes; see
# utils/portal.ts in the exported app.
#
# standard_portal_menu_items is the other door, and the wrong one: it syncs into Portal
# Settings, whose sync drops every row that does not name an existing DocType, and four
# of these rows are views rather than records.
#
# `covers` is this app's own key, carried through the hook untouched. A detail page has
# no row of its own, so it lights its list's row: /borrower/loan/L-0001 is a loan
# account. A row added from Portal Settings has no such key and matches its route alone.
#
# No `role`. A borrower is authorised by the Portal Users table on their Customer, not
# by a role, so gating the menu on "Customer" would empty the sidebar for anyone linked
# by hand. The rows are a menu, not a permission: every page behind them asks
# portal.core.get_portal_customers() who is knocking.
#
# One row per page a borrower can actually open. PORTAL_PLAN.md section 6.7 keeps
# repayments, disbursements and charges as sections of a loan rather than as pages of
# their own, so the sidebar does not offer them.
portal_menu_items = [
	{"title": "Account overview", "route": "/borrower-portal/overview"},
	{"title": "Loan accounts", "route": "/borrower-portal/loans", "covers": "/borrower-portal/loan"},
	{
		"title": "Application",
		"route": "/borrower-portal/applications",
		"covers": "/borrower-portal/application",
	},
	{"title": "Statement of account", "route": "/borrower-portal/statement"},
	{"title": "Interest certificate", "route": "/borrower-portal/certificate"},
	{"title": "Personal details", "route": "/borrower-portal/profile"},
]

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "lending.utils.jinja_methods",
# 	"filters": "lending.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "lending.install.before_install"
after_install = "lending.install.after_install"

# Migrating re-imports the portal's Studio Pages from lending/studio/, and every
# exported record carries what this app ships rather than what the lender chose: a page
# comes back published: 1 whether or not the lender has the portal switched on. This
# puts the lender's own answer back.
after_migrate = [
	"lending.loan_management.doctype.lending_settings.lending_settings.sync_portal_pages",
]

# Uninstallation
# ------------

before_uninstall = "lending.install.before_uninstall"
# after_uninstall = "lending.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "lending.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Company": {
		"validate": "lending.overrides.company.validate_loan_tables",
	},
	"Sales Invoice": {
		"on_submit": [
			"lending.overrides.sales_invoice.generate_demand",
			"lending.overrides.sales_invoice.update_waived_amount_in_demand",
			"lending.overrides.sales_invoice.make_partner_charge_gl_entries",
			"lending.overrides.sales_invoice.make_suspense_gl_entry_for_charges",
		],
		"on_cancel": "lending.overrides.sales_invoice.cancel_demand",
		"validate": "lending.overrides.sales_invoice.validate",
	},
	"Custom Field": {
		"before_insert": "lending.overrides.custom_field.update_dimensions",
	},
	"Journal Entry": {
		"on_cancel": "lending.overrides.journal_entry.add_ignore_linked_doctypes_for_jv",
	},
}

accounting_dimension_doctypes = [
	"Loan",
	"Loan Disbursement",
	"Loan Interest Accrual",
	"Loan Demand",
	"Loan Repayment",
	"Loan Refund",
	"Sales Invoice",
	"Journal Entry",
]

repost_allowed_doctypes = [
	"Loan Repayment",
	"Loan Disbursement",
]
# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily_long": [
		"lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual.schedule_accrual",
		"lending.loan_management.doctype.process_loan_demand.process_loan_demand.process_daily_loan_demands",
		"lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall.create_process_loan_security_shortfall",
		"lending.loan_management.doctype.process_loan_classification.process_loan_classification.create_process_loan_classification",
		"lending.loan_management.doctype.loan.loan.auto_close_loc_loans",
		"lending.loan_management.doctype.process_loan_accounting.process_loan_accounting.process_loan_accounting",
		"lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts.send_auto_email",
	],
	"monthly_long": [
		"lending.loan_management.doctype.process_loan_restructure_limit.process_loan_restructure_limit.calculate_monthly_restructure_limit",
	],
	"hourly_long": [
		"lending.loan_management.doctype.loan_repayment.loan_repayment.process_pending_credit_notes",
		"lending.loan_management.utils.process_cancelled_gl_entries",
	],
}

bank_reconciliation_doctypes = [
	"Loan Repayment",
	"Loan Disbursement",
]

# Overriding Methods
# ------------------------------
get_matching_queries = "lending.loan_management.utils.get_matching_queries"

get_amounts_not_reflected_in_system_for_bank_reconciliation_statement = "lending.loan_management.utils.get_amounts_not_reflected_in_system_for_bank_reconciliation_statement"

get_payment_entries_for_bank_clearance = (
	"lending.loan_management.utils.get_payment_entries_for_bank_clearance"
)

get_entries_for_bank_clearance_summary = (
	"lending.loan_management.utils.get_entries_for_bank_clearance_summary"
)

get_entries_for_bank_reconciliation_statement = (
	"lending.loan_management.utils.get_entries_for_bank_reconciliation_statement"
)

# ERPNext doctypes for Global Search
global_search_doctypes = {
	"Default": [
		{"doctype": "Loan", "index": 44},
	],
}

update_gl_dict_with_app_based_fields = ["lending.overrides.gl_entry.update_value_date_in_gl_dict"]

#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "lending.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

ignore_links_on_delete = [
	"Bulk Repayment Log",
	"Days Past Due Log",
	"Loan Freeze Log",
	"Loan Limit Change Log",
	"Loan NPA Log",
	"Loan Restructure Limit Log",
	"Process Loan Classification",
	"Process Loan Demand",
	"Process Loan Interest Accrual",
	"Process Loan Security Shortfall",
]

# Request Events
# ----------------
# before_request = ["lending.utils.before_request"]
# after_request = ["lending.utils.after_request"]

# Job Events
# ----------
# before_job = ["lending.utils.before_job"]
# after_job = ["lending.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"lending.auth.validate"
# ]

# Tasks are called as method(doc) and need no @frappe.whitelist(), unlike Server Scripts.
workflow_methods = [
	{
		"name": "Convert to Loan Application",
		"method": "lending.loan_origination.doctype.loan_lead.loan_lead.convert_to_loan_application"
	},
	{
		"name": "Validate Cooling Period",
		"method": "lending.loan_origination.doctype.loan_lead.loan_lead.run_cooling_period_task"
	},
	{
		"name": "Validate Live Loan Limit",
		"method": "lending.loan_origination.doctype.loan_lead.applicant_exposure.run_live_loan_limit_task"
	},
	{
		"name": "Run Pre-Qualification Rules",
		"method": "lending.loan_origination.decisioning.run_pre_qualification_rules"
	},
	{
		"name": "Run Knockout Rules",
		"method": "lending.loan_origination.decisioning.run_knockout_rules"
	}
]

# The /apply tokens are a visitor's proof of a verified number, held in the cache.
# frappe.clear_cache() deletes every other key on the site -- a migrate, a DocType
# save, "Reload" -- which would strand everyone half way through the form.
persistent_cache_keys = ["portal-apply-*"]
