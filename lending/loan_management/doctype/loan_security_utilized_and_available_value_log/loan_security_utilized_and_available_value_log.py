# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate


class LoanSecurityUtilizedandAvailableValueLog(Document):
	pass


def create_loan_security_utilized_and_available_value_log(
	loan_security,
	trigger_doctype,
	trigger_document,
	on_trigger_doc_cancel,
	new_available_security_value=None,
	new_utilized_security_value=None,
	previous_available_security_value=None,
	previous_utilized_security_value=None,
):
	doc = frappe.new_doc("Loan Security Utilized and Available Value Log")

	doc.loan_security = loan_security
	doc.posting_date = nowdate()
	doc.trigger_doctype = trigger_doctype
	doc.trigger_document = trigger_document
	doc.trigger_document_docstatus = 2 if on_trigger_doc_cancel else 1

	old_available_security_value, old_utilized_security_value = frappe.db.get_value(
		"Loan Security", loan_security, ["available_security_value", "utilized_security_value"]
	)

	doc.new_utilized_security_value = new_utilized_security_value or old_utilized_security_value
	doc.new_available_security_value = new_available_security_value or old_available_security_value
	doc.previous_available_security_value = (
		previous_available_security_value or old_available_security_value
	)
	doc.previous_utilized_security_value = (
		previous_utilized_security_value or old_utilized_security_value
	)

	doc.insert()
