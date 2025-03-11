# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate

from lending.loan_management.doctype.loan_demand.loan_demand import (
	get_open_loans,
	make_loan_demand_for_demand_loans,
	make_loan_demand_for_term_loans,
)


class ProcessLoanDemand(Document):
	def on_submit(self):
		BATCH_SIZE = 5000

		open_term_loans = get_open_loans(is_term_loan=1, loan_product=self.loan_product, loan=self.loan)
		open_demand_loans = get_open_loans(
			is_term_loan=0, loan_product=self.loan_product, loan=self.loan
		)

		for batch in get_batches(open_term_loans, BATCH_SIZE):
			frappe.enqueue(
				make_loan_demand_for_term_loans,
				posting_date=self.posting_date,
				loan_product=self.loan_product,
				loan=self.loan,
				process_loan_demand=self.name,
				loan_disbursement=self.loan_disbursement,
				loans=batch,
				queue="long",
				enqueue_after_commit=True,
			)

		for batch in get_batches(open_demand_loans, BATCH_SIZE):
			frappe.enqueue(
				make_loan_demand_for_demand_loans,
				posting_date=self.posting_date,
				loan=self.loan,
				process_loan_demand=self.name,
				loans=batch,
				queue="long",
				enqueue_after_commit=True,
			)


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
