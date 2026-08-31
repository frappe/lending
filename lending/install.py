import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

LOAN_CUSTOM_FIELDS = {
	"Sales Invoice": [
		{
			"fieldname": "loan",
			"label": "Loan",
			"fieldtype": "Link",
			"options": "Loan",
			"insert_after": "customer",
			"print_hide": 1,
		},
		{
			"fieldname": "loan_disbursement",
			"label": "Loan Disbursement",
			"fieldtype": "Link",
			"options": "Loan Disbursement",
			"insert_after": "loan",
			"read_only": 1,
			"print_hide": 1,
		},
		{
			"fieldname": "loan_repayment",
			"label": "Loan Repayment",
			"fieldtype": "Link",
			"options": "Loan Repayment",
			"insert_after": "loan_disbursement",
			"read_only": 1,
			"print_hide": 1,
		},
		{
			"fieldname": "value_date",
			"fieldtype": "Date",
			"label": "Value Date",
			"insert_after": "posting_date",
			"search_index": 1,
		},
	],
	"Company": [
		{
			"fieldname": "loan_tab",
			"fieldtype": "Tab Break",
			"label": "Lending",
			"insert_after": "default_scrap_warehouse",
		},
		{
			"fieldname": "loan_settings",
			"label": "Loan Settings",
			"fieldtype": "Section Break",
			"insert_after": "loan_tab",
		},
		{
			"fieldname": "loan_restructure_limit",
			"label": "Restructure Limit % (Overall)",
			"fieldtype": "Percent",
			"insert_after": "loan_settings",
		},
		{
			"fieldname": "watch_period_post_loan_restructure_in_days",
			"label": "Watch Period Post Loan Restructure (In Days)",
			"fieldtype": "Int",
			"insert_after": "loan_restructure_limit",
		},
		{
			"fieldname": "interest_day_count_convention",
			"label": "Interest Day-Count Convention",
			"fieldtype": "Select",
			"options": "Actual/365\nActual/Actual\n30/365\n30/360\nActual/360",
			"insert_after": "watch_period_post_loan_restructure_in_days",
		},
		{
			"fieldname": "min_days_bw_disbursement_first_repayment",
			"label": "Minimum days between Disbursement date and first Repayment date",
			"fieldtype": "Int",
			"insert_after": "interest_day_count_convention",
			"non_negative": 1,
		},
		{
			"fieldname": "loan_accrual_frequency",
			"label": "Loan Accrual Frequency",
			"fieldtype": "Select",
			"options": "Daily\nWeekly\nMonthly",
			"insert_after": "min_days_bw_disbursement_first_repayment",
		},
		{
			"fieldname": "loan_column_break",
			"fieldtype": "Column Break",
			"insert_after": "loan_accrual_frequency",
		},
		{
			"fieldname": "enable_loan_accounting",
			"label": "Enable Loan Accounting",
			"fieldtype": "Check",
			"insert_after": "loan_column_break",
		},
		{
			"fieldname": "enable_async_gl_reversal",
			"label": "Enable async reversal of GL for future demand and accruals",
			"fieldtype": "Check",
			"insert_after": "enable_loan_accounting",
		},
		{
			"fieldname": "async_gl_reversal_start_date",
			"label": "Async GL Reversal Start Date",
			"fieldtype": "Date",
			"depends_on": "enable_async_gl_reversal",
			"mandatory_depends_on": "enable_async_gl_reversal",
			"insert_after": "enable_async_gl_reversal",
		},
		{
			"fieldname": "collection_offset_logic_based_on",
			"label": "Collection Offset Logic Based On",
			"fieldtype": "Select",
			"options": "NPA Flag\nDays Past Due",
			"insert_after": "async_gl_reversal_start_date",
		},
		{
			"fieldname": "days_past_due_threshold",
			"label": "Days Past Due Threshold",
			"fieldtype": "Int",
			"insert_after": "collection_offset_logic_based_on",
			"non_negative": 1,
		},
		{
			"fieldname": "days_past_due_threshold_for_auto_write_off",
			"label": "Days Past Due Threshold For Auto Write Off",
			"fieldtype": "Int",
			"insert_after": "days_past_due_threshold",
			"non_negative": 1,
		},
		{
			"fieldname": "collection_offset_sequence_for_sub_standard_asset",
			"label": "Collection Offset Sequence for Sub Standard Asset",
			"fieldtype": "Link",
			"options": "Loan Demand Offset Order",
			"insert_after": "days_past_due_threshold_for_auto_write_off",
		},
		{
			"fieldname": "collection_offset_sequence_for_standard_asset",
			"label": "Collection Offset Sequence for Standard Asset",
			"fieldtype": "Link",
			"options": "Loan Demand Offset Order",
			"insert_after": "collection_offset_sequence_for_sub_standard_asset",
		},
		{
			"fieldname": "collection_offset_sequence_for_written_off_asset",
			"label": "Collection Offset Sequence for Written Off Asset",
			"fieldtype": "Link",
			"options": "Loan Demand Offset Order",
			"insert_after": "collection_offset_sequence_for_standard_asset",
		},
		{
			"fieldname": "collection_offset_sequence_for_settlement_collection",
			"label": "Collection Offset Sequence for Settlement Collection",
			"fieldtype": "Link",
			"options": "Loan Demand Offset Order",
			"insert_after": "collection_offset_sequence_for_written_off_asset",
		},
		{
			"fieldname": "loan_section_break_2",
			"fieldtype": "Section Break",
			"insert_after": "collection_offset_sequence_for_settlement_collection",
		},
		{
			"fieldname": "loan_classification_ranges",
			"label": "Loan Classification Ranges",
			"fieldtype": "Table",
			"options": "Loan Classification Range",
			"insert_after": "loan_section_break_2",
		},
		{
			"fieldname": "irac_provisioning_configuration",
			"label": "IRAC Provisioning Configuration",
			"fieldtype": "Table",
			"options": "Loan IRAC Provisioning Configuration",
			"insert_after": "loan_classification_ranges",
		},
	],
	"Customer": [
		{
			"fieldname": "loan_details_tab",
			"label": "Loan Details",
			"fieldtype": "Tab Break",
			"insert_after": "email_id",
		},
		{
			"fieldname": "is_npa",
			"label": "Is NPA",
			"fieldtype": "Check",
			"insert_after": "loan_details_tab",
		},
	],
	"Item Default": [
		{
			"fieldname": "loan_defaults_section",
			"fieldtype": "Section Break",
			"label": "Loan Defaults",
			"insert_after": "deferred_revenue_account",
		},
		{
			"fieldname": "default_receivable_account",
			"fieldtype": "Link",
			"label": "Default Receivable Account",
			"options": "Account",
			"insert_after": "loan_defaults_section",
		},
		{
			"fieldname": "default_waiver_account",
			"fieldtype": "Link",
			"label": "Default Waiver Account",
			"options": "Account",
			"insert_after": "default_receivable_account",
		},
		{
			"fieldname": "column_break_yajs",
			"fieldtype": "Column Break",
			"insert_after": "default_waiver_account",
		},
		{
			"fieldname": "default_write_off_account",
			"fieldtype": "Link",
			"label": "Default Write Off Account",
			"options": "Account",
			"insert_after": "column_break_yajs",
		},
		{
			"fieldname": "default_suspense_account",
			"fieldtype": "Link",
			"label": "Default Suspense Account",
			"options": "Account",
			"insert_after": "default_write_off_account",
		},
	],
	"Journal Entry": [
		{
			"fieldname": "loan_transfer",
			"fieldtype": "Link",
			"label": "Loan Transfer",
			"insert_after": "naming_series",
			"options": "Loan Transfer",
			"search_index": 1,
		},
		{
			"fieldname": "loan",
			"fieldtype": "Link",
			"label": "Loan",
			"insert_after": "loan_transfer",
			"options": "Loan",
			"search_index": 1,
		},
		{
			"fieldname": "value_date",
			"fieldtype": "Date",
			"label": "Value Date",
			"insert_after": "posting_date",
			"search_index": 1,
		},
	],
	"GL Entry": [
		{
			"fieldname": "value_date",
			"fieldtype": "Date",
			"label": "Value Date",
			"insert_after": "posting_date",
			"search_index": 1,
		},
	],
}


def make_property_setter_for_journal_entry():
	property_setter = frappe.db.get_value(
		"Property Setter",
		filters={
			"doc_type": "Journal Entry Account",
			"field_name": "reference_type",
			"property": "options",
		},
	)

	if property_setter:
		property_setter_doc = frappe.get_doc("Property Setter", property_setter)

		if "Loan Interest Accrual" not in property_setter_doc.value.split("\n"):
			property_setter_doc.value += "\n" + "Loan Interest Accrual"
			property_setter_doc.save()
	else:
		options = frappe.get_meta("Journal Entry Account").get_field("reference_type").options
		options += "\n" + "Loan Interest Accrual"

		make_property_setter(
			"Journal Entry Account",
			"reference_type",
			"options",
			options,
			"Text",
			validate_fields_for_doctype=False,
		)


def after_install():
	create_custom_fields(LOAN_CUSTOM_FIELDS, ignore_validate=True)
	make_property_setter_for_journal_entry()
	add_server_scripts()


def before_uninstall():
	delete_custom_fields(LOAN_CUSTOM_FIELDS)


# The Loan Lead basic rules, shipped as Server Scripts so a site can edit the rule
# itself -- change the number, add a condition, drop it entirely -- without forking the
# app. The two that call into Python keep the logic there, where it is tested; the script
# is the thin, editable bit. A number set on Loan Product still overrides what the script
# passes, so a site that only wants a different limit does not have to touch the script.
# The one place the age condition is written. The patch that guards an older, unguarded
# copy of this script replaces its condition with this one, so the two cannot drift.
GUARDED_AGE_CONDITION = 'if doc.applicant_type == "Individual" and (doc.age or 0) < 18:'

LOAN_LEAD_RULE_SCRIPTS = {
	"Age validation for Loan Lead": f"""
{GUARDED_AGE_CONDITION}
	frappe.throw("Applicant should be at least 18 years old.")
""",
	"Cooling period validation for Loan Lead": """
# An applicant rejected within this many days is held back. 0 turns the rule off.
# Cooling Period (Days) on the lead's Loan Product overrides this when set.
cooling_period_days = 30

frappe.call(
	"lending.loan_origination.doctype.loan_lead.loan_lead.validate_cooling_period",
	loan_lead=doc.name,
	cooling_period_days=cooling_period_days,
)
""",
	"Live loan limit validation for Loan Lead": """
# An applicant already holding this many live loans is held back. 0 turns the rule off.
# This is the only place the limit is set; it applies to every Loan Product.
maximum_live_loans = 0

frappe.call(
	"lending.loan_origination.doctype.loan_lead.applicant_exposure.validate_live_loan_limit",
	loan_lead=doc.name,
	maximum_live_loans=maximum_live_loans,
)
""",
}


def add_server_scripts():
	"""Create any shipped rule script a site does not have yet.

	Idempotent, and never touches a script that already exists: once a site has edited
	the rule, its copy wins. Safe to call from install and from a patch.
	"""
	for name, script in LOAN_LEAD_RULE_SCRIPTS.items():
		if frappe.db.exists("Server Script", name):
			continue

		doc = frappe.new_doc("Server Script")
		doc.name = name
		doc.script_type = "Workflow Task"
		doc.script = script
		doc.save(ignore_permissions=True)


def delete_custom_fields(custom_fields):
	"""
	:param custom_fields: a dict like `{'Customer': [{fieldname: 'test', ...}]}`
	"""

	for doctypes, fields in custom_fields.items():
		if isinstance(fields, dict):
			# only one field
			fields = [fields]

		if isinstance(doctypes, str):
			# only one doctype
			doctypes = (doctypes,)

		for doctype in doctypes:
			frappe.db.delete(
				"Custom Field",
				{
					"fieldname": ("in", [field["fieldname"] for field in fields]),
					"dt": doctype,
				},
			)

			frappe.clear_cache(doctype=doctype)
