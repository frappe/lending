# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from lending.loan_management.doctype.loan_demand.loan_demand import make_loan_demand_for_term_loans
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)


class ProcessLoanDemand(Document):
	def on_submit(self):
		filters = {}

		if self.loan_product:
			filters["loan_product"] = self.loan_product

		if self.loan:
			filters["loan"] = self.loan

		last_accrual_job_date = frappe.db.get_value(
			"Process Loan Interest Accrual", filters, "MAX(posting_date)"
		)

		if last_accrual_job_date and getdate(last_accrual_job_date) < getdate(self.posting_date):
			process_loan_interest_accrual_for_loans(
				posting_date=self.posting_date, loan_product=self.loan_product, loan=self.loan
			)

		make_loan_demand_for_term_loans(
			self.posting_date, loan_product=self.loan_product, loan=self.loan, process_loan_demand=self.name
		)


def process_daily_loan_demands(posting_date=None, loan_product=None, loan=None):
	loan_process = frappe.new_doc("Process Loan Demand")
	loan_process.posting_date = posting_date or nowdate()
	loan_process.loan_product = loan_product
	loan_process.loan = loan

	loan_process.submit()

	return loan_process.name
