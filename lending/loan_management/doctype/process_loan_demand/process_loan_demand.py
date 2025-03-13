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
		make_loan_demand_for_term_loans(
			self.posting_date,
			loan_product=self.loan_product,
			loan=self.loan,
			process_loan_demand=self.name,
			loan_disbursement=self.loan_disbursement,
		)
		make_loan_demand_for_demand_loans(
			self.posting_date,
			loan=self.loan,
			process_loan_demand=self.name,
		)


def process_daily_loan_demands(posting_date=None, loan_product=None, loan=None):
	loan_process = frappe.new_doc("Process Loan Demand")
	loan_process.posting_date = posting_date or nowdate()
	loan_process.loan_product = loan_product
	loan_process.loan = loan

	loan_process.submit()

	return loan_process.name
