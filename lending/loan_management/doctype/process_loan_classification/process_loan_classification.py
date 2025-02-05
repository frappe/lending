# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate


class ProcessLoanClassification(Document):
	def validate(self):
		if getdate(self.posting_date) < add_days(getdate(), -1):
			if not self.loan:
				frappe.throw(_("For backdated process loan classification, a Loan account is mandatory."))

			loan_product = frappe.get_value("Loan", self.loan, "loan_product")
			loc_loan_product = frappe.get_value("Loan Product", loan_product, "repayment_schedule_type")

			if not self.loan_disbursement and loc_loan_product == "Line of Credit":
				frappe.throw(_("For Line of Credit Loan, Loan Disbursement is mandatory."))

		if self.force_update_dpd_in_loan and not self.loan:
			frappe.throw(_("For force update DPD, a Loan account is mandatory."))

	def on_submit(self):
		filters = {
			"docstatus": 1,
			"status": ("in", ["Disbursed", "Partially Disbursed", "Active", "Written Off", "Settled"]),
		}

		if self.loan:
			filters["name"] = self.loan
			filters["status"] = (
				"in",
				["Disbursed", "Partially Disbursed", "Active", "Written Off", "Settled", "Closed"],
			)

		if self.loan_product:
			filters["loan_product"] = self.loan_product

		open_loans = frappe.get_all("Loan", filters=filters, pluck="name", order_by="applicant")

		if self.loan:
			process_loan_classification_batch(
				open_loans,
				self.posting_date,
				self.loan_product,
				self.name,
				self.loan_disbursement,
				self.payment_reference,
				self.is_backdated,
				self.force_update_dpd_in_loan,
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
					loan_disbursement=self.loan_disbursement,
					payment_reference=self.payment_reference,
					is_backdated=self.is_backdated,
					force_update_dpd_in_loan=self.force_update_dpd_in_loan,
					via_scheduler=True,
					queue="long",
					enqueue_after_commit=True,
				)


def process_loan_classification_batch(
	open_loans,
	posting_date,
	loan_product,
	classification_process,
	loan_disbursement,
	payment_reference,
	is_backdated,
	force_update_dpd_in_loan=False,
	via_scheduler=False,
):
	from lending.loan_management.doctype.loan.loan import update_days_past_due_in_loans

	for loan in open_loans:
		try:
			update_days_past_due_in_loans(
				loan_name=loan,
				posting_date=posting_date,
				loan_product=loan_product,
				process_loan_classification=classification_process,
				loan_disbursement=loan_disbursement,
				ignore_freeze=True if payment_reference else False,
				is_backdated=is_backdated,
				via_background_job=via_scheduler,
				force_update_dpd_in_loan=force_update_dpd_in_loan,
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
	posting_date=None,
	loan_product=None,
	loan=None,
	payment_reference=None,
	is_backdated=0,
	force_update_dpd_in_loan=0,
):
	posting_date = posting_date or add_days(getdate(), -1)
	process_loan_classification = frappe.new_doc("Process Loan Classification")
	process_loan_classification.posting_date = posting_date
	process_loan_classification.loan_product = loan_product
	process_loan_classification.loan = loan
	process_loan_classification.payment_reference = payment_reference
	process_loan_classification.is_backdated = is_backdated
	process_loan_classification.force_update_dpd_in_loan = force_update_dpd_in_loan
	process_loan_classification.submit()
