import frappe


def execute():
	LR = frappe.qb.DocType("Loan Repayment")

	(
		frappe.qb.update(LR)
		.set(LR.is_invoice_generated, 1)
		.where(
			(LR.repayment_type == "Charges Waiver")
			& (LR.docstatus == 1)
			& ((LR.is_invoice_generated.isnull()) | (LR.is_invoice_generated == 0))
		)
	).run()
