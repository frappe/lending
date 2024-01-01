import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	rename_field("Repayment Schedule", "is_accrued", "demand_generated")
	make_loan_demand_offset_order()


def make_loan_demand_offset_order():
	order = frappe.get_doc(
		{
			"doctype": "Loan Demand Offset Order",
			"title": "Standard Loan Demand Offset Order",
			"components": [
				{
					"demand_type": "Penalty",
				},
				{
					"demand_type": "Interest",
				},
				{
					"demand_type": "Principal",
				},
			],
		}
	).insert()

	for company in frappe.get_all("Company"):
		doc = frappe.get_doc("Company", company.name)
		if not doc.get("collection_offset_sequence_for_standard_asset"):
			doc.collection_offset_sequence_for_standard_asset = order.name

		if not doc.get("collection_offset_sequence_for_sub_standard_asset"):
			doc.collection_offset_sequence_for_non_standard_asset = order.name

		if not doc.get("collection_offset_sequence_for_written_off_asset"):
			doc.collection_offset_sequence_for_written_off_asset = order.name

		if not doc.get("collection_offset_sequence_for_settlement_collection"):
			doc.collection_offset_sequence_for_settlement_collection = order.name

	doc.save()
