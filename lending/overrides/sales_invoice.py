import frappe
from frappe.utils import flt

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	create_loan_demand,
)


def generate_demand(self, method=None):
	if self.get("loan") and not self.get("loan_disbursement") and not self.get("is_return"):
		for item in self.get("items"):
			tax_amount = get_tax_amount(self.get("taxes"), item.item_code)
			demand_amount = item.base_net_amount + tax_amount
			create_loan_demand(
				self.loan, self.posting_date, "Charges", item.item_code, demand_amount, sales_invoice=self.name
			)


def update_waived_amount_in_demand(self, method=None):
	if self.get("is_return"):
		for item in self.get("items"):
			tax_amount = get_tax_amount(self.get("taxes"), item.item_code)
			waived_amount = abs(item.base_net_amount + tax_amount)
			demand_details = frappe.db.get_value(
				"Loan Demand",
				{"loan": self.loan, "docstatus": 1, "demand_subtype": item.item_code},
				["name", "outstanding_amount"],
				as_dict=1,
			)

			if demand_details:
				if flt(demand_details.outstanding_amount) - flt(waived_amount) < 0:
					frappe.throw("Waived amount cannot be greater than outstanding amount")

				if flt(demand_details.outstanding_amount) > flt(waived_amount):
					loan_demand = frappe.qb.DocType("Loan Demand")
					frappe.qb.update(loan_demand).set(
						loan_demand.waived_amount, loan_demand.waived_amount + waived_amount
					).set(
						loan_demand.outstanding_amount, loan_demand.outstanding_amount - waived_amount
					).where(
						loan_demand.name == demand_details.name
					).run()


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
