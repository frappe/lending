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
			"read_only": 1,
		}
	],
	"Company": [
		{
			"fieldname": "loan_tab",
			"fieldtype": "Tab Break",
			"label": "Loan",
			"insert_after": "expenses_included_in_valuation",
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
			"fieldname": "min_bpi_application_days",
			"label": "Minimum Days for Broken Period Interest Application",
			"fieldtype": "Int",
			"insert_after": "interest_day_count_convention",
		},
		{
			"fieldname": "loan_column_break",
			"fieldtype": "Column Break",
			"insert_after": "min_bpi_application_days",
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
			"fieldname": "loan_section_break_2",
			"fieldtype": "Section Break",
			"insert_after": "collection_offset_sequence_for_written_off_asset",
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
			"insert_after": "primary_address",
		},
		{
			"fieldname": "is_npa",
			"label": "Is NPA",
			"fieldtype": "Check",
			"insert_after": "loan_details_tab",
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


def before_uninstall():
	delete_custom_fields(LOAN_CUSTOM_FIELDS)


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
