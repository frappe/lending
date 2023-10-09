# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class ProcessLoanClassification(Document):
	def on_submit(self):
		from lending.loan_management.doctype.loan.loan import update_days_past_due_in_loans

		update_days_past_due_in_loans(
			posting_date=self.posting_date,
			loan_product=self.loan_product,
			loan_name=self.loan,
			process_loan_classification=self.name,
		)


def create_process_loan_classification(
	posting_date=None, loan_product=None, loan=None, payment_reference=None
):
	posting_date = posting_date or getdate()

	previous_process = frappe.db.get_all(
		"Process Loan Classification",
		filters={"posting_date": ("<=", posting_date), "loan": ("in", ["", loan])},
		fields=["name"],
		order_by="posting_date desc",
		limit=1,
	)

	process_loan_classification = frappe.new_doc("Process Loan Classification")
	process_loan_classification.posting_date = posting_date
	process_loan_classification.loan_product = loan_product
	process_loan_classification.loan = loan
	process_loan_classification.previous_process = (
		previous_process[0].name if previous_process else None
	)
	process_loan_classification.payment_reference = payment_reference
	process_loan_classification.submit()
