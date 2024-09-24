# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class ProcessLoanClassification(Document):
	def on_submit(self):
		from lending.loan_management.doctype.loan.loan import update_days_past_due_in_loans

		filters = {
			"docstatus": 1,
			"status": ("in", ["Disbursed", "Partially Disbursed", "Active", "Written Off", "Settled"]),
		}

		if self.loan:
			filters["name"] = self.loan

		if self.loan_product:
			filters["loan_product"] = self.loan_product

		open_loans = frappe.get_all("Loan", filters=filters, pluck="name")

		frappe.db.auto_commit_on_many_writes = 1

		for loan in open_loans:
			try:
				update_days_past_due_in_loans(
					loan_name=loan,
					posting_date=self.posting_date,
					loan_product=self.loan_product,
					process_loan_classification=self.name,
					ignore_freeze=True if self.payment_reference else False,
					is_backdated=self.is_backdated,
				)
			except Exception as e:
				if len(open_loans) == 1:
					raise e
				else:
					frappe.log_error(
						title="Process Loan Classification Error",
						message=frappe.get_traceback(),
						reference_doctype="Loan",
						reference_name=loan,
					)

		frappe.db.auto_commit_on_many_writes = 0


def create_process_loan_classification(
	posting_date=None, loan_product=None, loan=None, payment_reference=None, is_backdated=0
):
	posting_date = posting_date or getdate()
	process_loan_classification = frappe.new_doc("Process Loan Classification")
	process_loan_classification.posting_date = posting_date
	process_loan_classification.loan_product = loan_product
	process_loan_classification.loan = loan
	process_loan_classification.payment_reference = payment_reference
	process_loan_classification.is_backdated = is_backdated
	process_loan_classification.submit()
