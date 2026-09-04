import frappe

from lending.loan_origination.doctype.loan_lead.loan_lead import REJECTED_WORKFLOW_STATE


def execute():
	if not frappe.db.has_column("Loan Lead", "workflow_state"):
		return

	loan_lead = frappe.qb.DocType("Loan Lead")
	(
		frappe.qb.update(loan_lead)
		.set(loan_lead.rejected_on, loan_lead.modified)
		.where(loan_lead.workflow_state == REJECTED_WORKFLOW_STATE)
		.where(loan_lead.rejected_on.isnull())
	).run()
