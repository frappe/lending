# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

from lending.loan_management.doctype.loan_restructure.loan_restructure import create_loan_repayment


class LoanAdjustment(Document):
	def on_submit(self):
		for repayment in self.get("adjustments"):
			create_loan_repayment(
				self.loan, self.posting_date, repayment.loan_repayment_type, repayment.amount
			)
