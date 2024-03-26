import frappe
from frappe.utils import flt

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	create_loan_demand,
)


def generate_demand(self, method=None):
	if self.get("loan") and not self.get("loan_disbursement"):
		for item in self.get("items"):
			tax_amount = get_tax_amount(self.get("taxes"), item.item_code)
			demand_amount = item.base_net_amount + tax_amount
			create_loan_demand(
				self.loan, self.posting_date, "Charges", item.item_code, demand_amount, sales_invoice=self.name
			)


def cancel_demand(self, method=None):
	if self.get("loan"):
		demand = frappe.db.get_value("Loan Demand", {"sales_invoice": self.name})
		if demand:
			frappe.get_doc("Loan Demand", demand).cancel()


def get_tax_amount(taxes, item_code):
	tax_amount = 0
	for tax in taxes:
		if tax.item_wise_tax_detail:
			item_wise_tax_detail = frappe.parse_json(tax.item_wise_tax_detail)
			if item_wise_tax_detail.get(item_code):
				tax_amount += flt(item_wise_tax_detail.get(item_code)[1])

	return tax_amount


def validate(doc, method):
	if doc.get("loan"):
		doc.against_voucher_type = "Loan"
		doc.against_voucher = doc.loan
