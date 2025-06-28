import json

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.general_ledger import make_gl_entries

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	create_loan_demand,
)


def generate_demand(self, method=None):
	if self.get("loan") and not self.get("loan_disbursement") and not self.get("is_return"):
		total_demand_amount = 0
		total_items = len(self.get("items") or [])
		for i, item in enumerate(self.get("items")):
			tax_amount = get_tax_amount(self.get("taxes"), item.item_code)
			demand_amount = item.base_net_amount + flt(tax_amount)
			total_demand_amount += demand_amount
			if i == total_items - 1:
				precision_diff = self.rounded_total - total_demand_amount
				if precision_diff > 0:
					demand_amount += flt(precision_diff, 2)

			create_loan_demand(
				self.loan,
				self.posting_date,
				"Charges",
				item.item_code,
				flt(demand_amount, 2),
				sales_invoice=self.name,
			)


def update_waived_amount_in_demand(self, method=None):
	if self.get("is_return") and not self.get("loan_repayment"):
		for item in self.get("items"):
			tax_amount = get_tax_amount(self.get("taxes"), item.item_code)
			waived_amount = abs(item.base_net_amount + tax_amount)
			demand_details = frappe.db.get_value(
				"Loan Demand",
				{
					"loan": self.loan,
					"docstatus": 1,
					"demand_subtype": item.item_code,
					"sales_invoice": self.get("return_against"),
				},
				["name", "outstanding_amount"],
				as_dict=1,
			)

			if demand_details:
				if flt(demand_details.outstanding_amount) - flt(waived_amount) < 0:
					frappe.throw(_("Waived amount cannot be greater than outstanding amount"))

				if flt(demand_details.outstanding_amount) > flt(waived_amount):
					loan_demand = frappe.qb.DocType("Loan Demand")
					frappe.qb.update(loan_demand).set(
						loan_demand.waived_amount, loan_demand.waived_amount + waived_amount
					).set(
						loan_demand.outstanding_amount, loan_demand.outstanding_amount - waived_amount
					).where(
						loan_demand.name == demand_details.name
					).run()


def make_partner_charge_gl_entries(doc, method):
	if doc.get("loan_partner"):
		accounting_enabled = frappe.db.get_value(
			"Loan Partner", doc.loan_partner, "enable_partner_accounting"
		)

		if not accounting_enabled:
			return

		gl_entries = []
		partner_details = frappe._dict(
			frappe.db.get_all(
				"Loan Partner Shareable",
				filters={"parent": doc.loan_partner},
				fields=["shareable_type", "partner_collection_percentage"],
				as_list=1,
			)
		)

		partner_payable_account = frappe.db.get_value(
			"Loan Partner", doc.loan_partner, "payable_account"
		)

		for item in doc.get("items"):
			share_percentage = partner_details.get(item.item_code, 0)
			income_amount = item.base_amount * share_percentage / 100

			if income_amount > 0:
				gl_entries = make_partner_gl_entries(
					doc, item, income_amount, item.income_account, partner_payable_account, gl_entries
				)

		for tax in doc.get("taxes"):
			item_details = json.loads(tax.item_wise_tax_detail)
			for item_code, tax_amount in item_details.items():
				share_percentage = partner_details.get(item_code, 0)
				tax_amount = tax_amount[1] * share_percentage / 100
				if tax_amount > 0:
					gl_entries = make_partner_gl_entries(
						doc, item, tax_amount, tax.account_head, partner_payable_account, gl_entries
					)

		make_gl_entries(gl_entries)


def make_suspense_gl_entry_for_charges(doc, method):
	from lending.loan_management.doctype.loan.loan import move_receivable_charges_to_suspense_ledger

	is_npa = frappe.db.get_value("Loan", doc.loan, "is_npa")
	if is_npa:
		move_receivable_charges_to_suspense_ledger(
			doc.loan, doc.company, doc.posting_date, invoice=doc.name
		)


def make_partner_gl_entries(
	doc, item, amount, item_tax_account, partner_payable_account, gl_entries
):
	gl_entries.append(
		doc.get_gl_dict(
			{
				"account": item_tax_account,
				"against": doc.customer,
				"debit": amount,
				"debit_in_account_currency": amount,
				"cost_center": item.cost_center,
				"project": item.project or doc.project,
			},
			item=item,
		)
	)
	gl_entries.append(
		doc.get_gl_dict(
			{
				"account": partner_payable_account,
				"against": doc.customer,
				"credit": amount,
				"credit_in_account_currency": amount,
				"cost_center": item.cost_center,
				"project": item.project or doc.project,
			},
			item=item,
		)
	)

	return gl_entries


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
