# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate


class LoanCollateralValuesLog(Document):
	pass


def create_loan_collateral_values_log(
	loan_collateral,
	trigger_doctype,
	trigger_document,
	on_trigger_doc_cancel,
	new_available_collateral_value,
	new_utilized_collateral_value,
	previous_available_collateral_value,
	previous_utilized_collateral_value,
):
	doc = frappe.new_doc("Loan Collateral Values Log")

	doc.loan_collateral = loan_collateral
	doc.posting_date = nowdate()
	doc.trigger_doctype = trigger_doctype
	doc.trigger_document = trigger_document
	doc.trigger_document_docstatus = 2 if on_trigger_doc_cancel else 1

	doc.new_available_collateral_value = new_available_collateral_value
	doc.new_utilized_collateral_value = new_utilized_collateral_value
	doc.previous_available_collateral_value = previous_available_collateral_value
	doc.previous_utilized_collateral_value = previous_utilized_collateral_value

	doc.insert()
