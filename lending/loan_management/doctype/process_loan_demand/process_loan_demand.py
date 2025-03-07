# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate

from lending.loan_management.doctype.loan_demand.loan_demand import (
	make_loan_demand_for_demand_loans,
	make_loan_demand_for_term_loans,
)


class ProcessLoanDemand(Document):
	def on_submit(self):
		filters = {
			"docstatus": 1,
			"status": ("in", ["Disbursed", "Partially Disbursed", "Active", "Written Off", "Settled"]),
		}

		if self.loan:
			filters["name"] = self.loan
			filters["status"] = (
				"in",
				["Disbursed", "Partially Disbursed", "Active", "Written Off", "Settled"],
			)

		if self.loan_product:
			filters["loan_product"] = self.loan_product

		open_loans = frappe.get_all("Loan", filters=filters, pluck="name", order_by="applicant")

		if self.loan:
			process_loan_demand_batch(
				open_loans=open_loans,
				posting_date=self.posting_date,
				loan_product=self.loan_product,
				process_loan_demand=self.name,
				loan_disbursement=self.loan_disbursement,
			)
		else:
			BATCH_SIZE = 5000
			batch_list = list(get_batches(open_loans, BATCH_SIZE))

			for batch in batch_list:
				frappe.enqueue(
					process_loan_demand_batch,
					open_loans=batch,
					posting_date=self.posting_date,
					loan_product=self.loan_product,
					process_loan_demand=self.name,
					loan_disbursement=self.loan_disbursement,
					queue="long",
					enqueue_after_commit=True,
				)


def process_loan_demand_batch(
	open_loans,
	posting_date,
	loan_product,
	process_loan_demand,
	loan_disbursement,
):

	for loan in open_loans:
		try:
			make_loan_demand_for_term_loans(
				posting_date,
				loan_product=loan_product,
				loan=loan,
				process_loan_demand=process_loan_demand,
				loan_disbursement=loan_disbursement,
			)

			make_loan_demand_for_demand_loans(
				posting_date,
				loan=loan,
				process_loan_demand=process_loan_demand,
			)
		except Exception as e:
			frappe.log_error(f"Error processing loan {loan}: {str(e)}")


def get_batches(open_loans, batch_size):
	for i in range(0, len(open_loans), batch_size):
		yield open_loans[i : i + batch_size]


def process_daily_loan_demands(posting_date=None, loan_product=None, loan=None):
	loan_process = frappe.new_doc("Process Loan Demand")
	loan_process.posting_date = posting_date or nowdate()
	loan_process.loan_product = loan_product
	loan_process.loan = loan

	loan_process.submit()

	return loan_process.name
