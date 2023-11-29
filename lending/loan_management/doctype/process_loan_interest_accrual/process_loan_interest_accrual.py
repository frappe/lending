# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.utils import nowdate

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	make_accrual_interest_entry_for_loans,
)


class ProcessLoanInterestAccrual(Document):
	def on_submit(self):
		open_loans = []

		if self.loan:
			loan_doc = frappe.get_doc("Loan", self.loan)
			if loan_doc:
				open_loans.append(loan_doc)

			make_accrual_interest_entry_for_loans(
				self.posting_date,
				self.name,
				open_loans=open_loans,
				loan_product=self.loan_product,
				accrual_type=self.accrual_type,
			)


def process_loan_interest_accrual_for_loans(
	posting_date=None, loan_product=None, loan=None, accrual_type="Regular"
):
	loan_process = frappe.new_doc("Process Loan Interest Accrual")
	loan_process.posting_date = posting_date or nowdate()
	loan_process.loan_product = loan_product
	loan_process.loan = loan
	loan_process.accrual_type = accrual_type

	loan_process.submit()

	return loan_process.name
