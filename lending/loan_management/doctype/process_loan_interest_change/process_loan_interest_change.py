# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProcessLoanInterestChange(Document):
	def on_submit(self):
		loan = frappe.qb.DocType("Loan")
		if self.loan_product:
			frappe.qb.update(loan).set(loan.rate_of_interest, self.new_rate_of_interest).where(
				loan.status.isin(["Disbursed", "Partially Disbursed", "Sanctioned"])
			).run()
		elif self.get("loans"):
			loans = [d.loan for d in self.get("loans")]
			frappe.qb.update(loan).set(loan.rate_of_interest, self.new_rate_of_interest).where(
				(loan.status.isin(loans))
				& (loan.status.isin(["Disbursed", "Partially Disbursed", "Sanctioned"]))
			).run()
