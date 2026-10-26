# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, formatdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	calculate_amounts,
	get_moratorium_end_date,
)


class SaleProceeds:
	def __init__(self, sale, proceeds_date):
		self.sale = sale
		self.proceeds_date = proceeds_date

	def apply(self):
		disbursements = self.get_disbursements()
		if not disbursements and flt(self.sale.charges):
			frappe.throw(
				_(
					"Loan {0} has no open disbursement to book the sale charge against. Cancel and amend this sale without the charge to apply the proceeds"
				).format(frappe.bold(self.sale.loan))
			)
		# A drawdown's repayment reads only that drawdown's demands, so the fee rides on the first one paid
		self.book_charges(disbursements[0] if disbursements else None)
		remaining = flt(self.sale.gross_proceeds) - flt(self.sale.deductions)
		for disbursement in disbursements:
			if remaining <= 0:
				break
			payable_amount = flt(self.get_amounts(disbursement, "Loan Closure")["payable_amount"])
			amount = min(remaining, payable_amount)
			if amount > 0:
				self.repay(disbursement, amount, payable_amount)
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

	def repay(self, disbursement, amount, closure_amount):
		repayment_type = self.get_repayment_type(disbursement, amount, closure_amount)
		repayment = frappe.get_doc(
			{
				"doctype": "Loan Repayment",
				"against_loan": self.sale.loan,
				"loan_disbursement": disbursement,
				"company": self.sale.company,
				"posting_date": self.proceeds_date,
				"value_date": self.proceeds_date,
				"amount_paid": amount,
				"repayment_type": repayment_type,
				"reference_number": self.sale.name,
				"reference_date": self.proceeds_date,
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

	def get_repayment_type(self, disbursement, amount, closure_amount):
		# A product can cap Normal Repayment at the dues; Pre Payment takes the rest as principal
		dues = flt(self.get_amounts(disbursement)["payable_amount"])
		if flt(amount, 2) <= flt(dues, 2):
			return "Normal Repayment"

		moratorium_end_date = get_moratorium_end_date(self.sale.loan, self.proceeds_date)
		if not moratorium_end_date:
			return "Pre Payment"

		# A moratorium bars Pre Payment but not closure, which accepts a shortfall up to the write-off amount
		loan_product = frappe.db.get_value("Loan", self.sale.loan, "loan_product")
		write_off_amount = frappe.get_cached_value("Loan Product", loan_product, "write_off_amount")
		if flt(amount, 2) >= flt(flt(closure_amount) - flt(write_off_amount), 2):
			return "Loan Closure"
		currency = frappe.get_cached_value("Company", self.sale.company, "default_currency")
		frappe.throw(
			_(
				"Loan {0} is in moratorium until {1}. The proceeds exceed the dues of {2} but do not close the loan, so apply them with a Proceeds Date after the moratorium ends"
			).format(
				frappe.bold(self.sale.loan),
				frappe.bold(formatdate(moratorium_end_date)),
				frappe.bold(fmt_money(dues, currency=currency)),
			),
			title=_("Loan in moratorium"),
		)

	def get_amounts(self, disbursement, payment_type=None):
		return calculate_amounts(
			self.sale.loan,
			self.proceeds_date,
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
				self.proceeds_date,
				sale.company,
				[frappe._dict(charge=charge, amount=sale.charges)],
			)
			# The invoice's own loan_disbursement would stop it raising the demand, so tag the demand instead
			if disbursement:
				demands = frappe.get_all(
					"Loan Demand", filters={"sales_invoice": voucher.name, "docstatus": 1}, pluck="name"
				)
				if not demands:
					frappe.throw(
						_("Sales Invoice {0} raised no Loan Demand for the sale charge").format(
							frappe.bold(voucher.name)
						)
					)
				for demand in demands:
					frappe.db.set_value("Loan Demand", demand, "loan_disbursement", disbursement)
		else:
			voucher = create_loan_demand(
				loan=sale.loan,
				demand_date=self.proceeds_date,
				demand_type="Charges",
				demand_subtype=charge,
				amount=sale.charges,
				loan_disbursement=disbursement,
			)
		sale.db_set({"charge_voucher_type": voucher.doctype, "charge_voucher": voucher.name})
