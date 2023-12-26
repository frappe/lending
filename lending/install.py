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
		}
	],
	"Company": [
		{
			"fieldname": "loan_tab",
			"fieldtype": "Tab Break",
			"label": "Loan",
			"insert_after": "default_in_transit_warehouse",
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
			"fieldname": "loan_column_break",
			"fieldtype": "Column Break",
			"insert_after": "min_days_bw_disbursement_first_repayment",
		},
		{
			"fieldname": "collection_offset_logic_based_on",
			"label": "Collection Offset Logic Based On",
			"fieldtype": "Select",
			"options": "NPA Flag\nDays Past Due",
			"insert_after": "loan_column_break",
		},
		{
			"fieldname": "days_past_due_threshold",
			"label": "Days Past Due Threshold",
			"fieldtype": "Int",
			"insert_after": "collection_offset_logic_based_on",
			"non_negative": 1,
		},
		{
			"fieldname": "collection_offset_sequence_for_sub_standard_asset",
			"label": "Collection Offset Sequence for Sub Standard Asset",
			"fieldtype": "Select",
			"options": "IP...IP...IP...CCC\nPPP...III...CCC",
			"insert_after": "days_past_due_threshold",
		},
		{
			"fieldname": "collection_offset_sequence_for_standard_asset",
			"label": "Collection Offset Sequence for Standard Asset",
			"fieldtype": "Select",
			"options": "IP...IP...IP...CCC\nPPP...III...CCC",
			"insert_after": "collection_offset_sequence_for_sub_standard_asset",
		},
		{
			"fieldname": "collection_offset_sequence_for_written_off_asset",
			"label": "Collection Offset Sequence for Written Off Asset",
			"fieldtype": "Select",
			"options": "IP...IP...IP...CCC\nPPP...III...CCC",
			"insert_after": "collection_offset_sequence_for_standard_asset",
		},
		{
			"fieldname": "collection_offset_sequence_for_settlement_collection",
			"label": "Collection Offset Sequence for Settlement Collection",
			"fieldtype": "Select",
			"options": "IP...IP...IP...CCC\nPPP...III...CCC",
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


def get_post_install_patches():
	return (
		"rename_loan_type_to_loan_product",
		"generate_loan_repayment_schedule",
		"update_loan_types",
		"make_loan_type_non_submittable",
		"migrate_loan_type_to_loan_product",
		"add_loan_product_code_and_rename_loan_name",
		"update_penalty_interest_method_in_loan_products",
	)


def run_patches(patches):
	frappe.flags.in_patch = True

	try:
		for patch in patches:
			frappe.get_attr(f"lending.patches.v15_0.{patch}.execute")()
	finally:
		frappe.flags.in_patch = False


def after_install():
	create_custom_fields(LOAN_CUSTOM_FIELDS, ignore_validate=True)
	make_property_setter_for_journal_entry()
	print("\nRunning post-install patches to patch existing data...\n")
	run_patches(get_post_install_patches())
