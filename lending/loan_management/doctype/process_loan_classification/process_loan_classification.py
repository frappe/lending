# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class ProcessLoanClassification(Document):
	def on_submit(self):
		filters = {
			"docstatus": 1,
			"status": ("in", ["Disbursed", "Partially Disbursed", "Active", "Written Off", "Settled"]),
		}

		if self.loan:
			filters["name"] = self.loan

		if self.loan_product:
			filters["loan_product"] = self.loan_product

		open_loans = frappe.get_all("Loan", filters=filters, pluck="name")

		if self.loan:
			process_loan_classification_batch(
				open_loans,
				self.posting_date,
				self.loan_product,
				self.name,
				self.payment_reference,
				self.is_backdated,
			)
		else:
			BATCH_SIZE = 5000
			batch_list = list(get_batches(open_loans, BATCH_SIZE))
			for batch in batch_list:
				frappe.enqueue(
					process_loan_classification_batch,
					open_loans=batch,
					posting_date=self.posting_date,
					loan_product=self.loan_product,
					classification_process=self.name,
					payment_reference=self.payment_reference,
					is_backdated=self.is_backdated,
					queue="long",
				)


def process_loan_classification_batch(
	open_loans, posting_date, loan_product, classification_process, payment_reference, is_backdated
):
	from lending.loan_management.doctype.loan.loan import update_days_past_due_in_loans

	for loan in open_loans:
		try:
			update_days_past_due_in_loans(
				loan_name=loan,
				posting_date=posting_date,
				loan_product=loan_product,
				process_loan_classification=classification_process,
				ignore_freeze=True if payment_reference else False,
				is_backdated=is_backdated,
			)

			if len(open_loans) > 1:
				frappe.db.commit()
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
				frappe.db.rollback()


def get_batches(open_loans, batch_size):
	for i in range(0, len(open_loans), batch_size):
		yield open_loans[i : i + batch_size]


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
