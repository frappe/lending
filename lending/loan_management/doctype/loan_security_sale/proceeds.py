# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts


class SaleProceeds:
	"""Charges the sale fee and repays the loan from a submitted sale's gross proceeds."""

	def __init__(self, sale):
		self.sale = sale

	def apply(self):
		"""Repay each open disbursement in turn and return the surplus left for the borrower."""
		disbursements = self.get_disbursements()
		# A drawdown's repayment reads only that drawdown's demands, so the fee rides on the first one paid
		self.book_charges(disbursements[0] if disbursements else None)
		remaining = flt(self.sale.gross_proceeds)
		for disbursement in disbursements:
			if remaining <= 0:
				break
			payable_amount = flt(self.get_amounts(disbursement, "Loan Closure")["payable_amount"])
			amount = min(remaining, payable_amount)
			if amount > 0:
				self.repay(disbursement, amount)
				remaining -= amount
		return remaining

	def get_disbursements(self):
		# A Line of Credit repayment must name the drawdown it pays, so pay the oldest first
		if frappe.db.get_value("Loan", self.sale.loan, "repayment_schedule_type") != "Line of Credit":
			return [None]
		return frappe.get_all(
			"Loan Disbursement",
			filters={"against_loan": self.sale.loan, "docstatus": 1, "status": ("!=", "Closed")},
			order_by="disbursement_date, creation",
			pluck="name",
		)

	def repay(self, disbursement, amount):
		# A product can cap Normal Repayment at the dues; Pre Payment takes the rest as principal
		dues = flt(self.get_amounts(disbursement)["payable_amount"])
		repayment_type = "Normal Repayment" if flt(amount, 2) <= flt(dues, 2) else "Pre Payment"

		repayment = frappe.get_doc(
			{
				"doctype": "Loan Repayment",
				"against_loan": self.sale.loan,
				"loan_disbursement": disbursement,
				"company": self.sale.company,
				"posting_date": self.sale.posting_date,
				"value_date": self.sale.posting_date,
				"amount_paid": amount,
				"repayment_type": repayment_type,
				"reference_number": self.sale.name,
				"reference_date": self.sale.posting_date,
			}
		).insert()
		repayment.submit()

		row = self.sale.append(
			"repayments",
			{
				"loan_repayment": repayment.name,
				"loan_disbursement": disbursement,
				"repayment_type": repayment_type,
				"amount": amount,
			},
		)
		row.db_insert()

	def get_amounts(self, disbursement, payment_type=None):
		return calculate_amounts(
			self.sale.loan,
			self.sale.posting_date,
			payment_type=payment_type,
			loan_disbursement=disbursement,
		)

	def book_charges(self, disbursement):
		from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
		from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
			make_sales_invoice_for_charge,
		)
		from lending.loan_management.utils import loan_accounting_enabled

		sale = self.sale
		if not flt(sale.charges):
			return

		charge = frappe.db.get_single_value("Lending Settings", "sale_charge")
		if loan_accounting_enabled(sale.company):
			voucher = make_sales_invoice_for_charge(
				sale.loan,
				"remarks",
				_("Sale charge for Loan Security Sale {0}").format(sale.name),
				sale.applicant if sale.applicant_type == "Customer" else None,
				sale.posting_date,
				sale.company,
				[frappe._dict(charge=charge, amount=sale.charges)],
			)
			# The invoice's own loan_disbursement would stop it raising the demand, so tag the demand instead
			if disbursement:
				frappe.db.set_value(
					"Loan Demand", {"sales_invoice": voucher.name}, "loan_disbursement", disbursement
				)
		else:
			voucher = create_loan_demand(
				loan=sale.loan,
				demand_date=sale.posting_date,
				demand_type="Charges",
				demand_subtype=charge,
				amount=sale.charges,
				loan_disbursement=disbursement,
			)
		sale.db_set({"charge_voucher_type": voucher.doctype, "charge_voucher": voucher.name})
