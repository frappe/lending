import frappe

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	create_loan_demand,
)


def generate_demand(self, method=None):
	if self.get("loan"):
		create_loan_demand(
			self.loan, self.posting_date, "Charges", "Charges", self.grand_total, sales_invoice=self.name
		)


def cancel_demand(self, method=None):
	if self.get("loan"):
		demand = frappe.db.get_value("Loan Demand", {"sales_invoice": self.name})
		if demand:
			frappe.get_doc("Loan Demand", demand).cancel()
