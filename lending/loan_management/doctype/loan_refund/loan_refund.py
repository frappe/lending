# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_repayment.loan_repayment import get_net_paid_amount


class LoanRefund(AccountsController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		applicant: DF.DynamicLink | None
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		company: DF.Link
		cost_center: DF.Link | None
		is_excess_amount_refund: DF.Check
		is_security_amount_refund: DF.Check
		loan: DF.Link
		loan_product: DF.Link | None
		posting_date: DF.Date
		reference_number: DF.Data | None
		refund_account: DF.Link
		refund_amount: DF.Currency
		value_date: DF.Date
	# end: auto-generated types

	"""
	Add refund if total repayment is more than that is owed.
	"""

	def validate(self):
		self.posting_date = getdate()
		self.set_missing_values()
		# self.validate_refund_amount()

	def set_missing_values(self):
		if not self.cost_center:
			self.cost_center = erpnext.get_default_cost_center(self.company)

	def validate_refund_amount(self):
		net_paid_amount = get_net_paid_amount(self.loan)

		if net_paid_amount - self.refund_amount < 0:
			frappe.throw(_("Refund amount cannot be greater than net paid amount"))

	def on_submit(self):
		self.update_outstanding_amount()
		self.make_gl_entries()

	def on_cancel(self):
		self.update_outstanding_amount(cancel=1)
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries(cancel=1)

	def update_outstanding_amount(self, cancel=0):
		security_deposit_available_amount = 0

		if self.is_excess_amount_refund:
			fieldname = "excess_amount_paid"
			amount = -1 * self.refund_amount
		elif self.is_security_amount_refund:
			security_deposit_available_amount = frappe.db.get_value(
				"Loan Security Deposit", {"loan": self.loan}, "available_amount"
			)

			fieldname = "refund_amount"
			amount = self.refund_amount
		else:
			fieldname = "refund_amount"
			amount = self.refund_amount

		refund_amount = frappe.db.get_value("Loan", self.loan, fieldname)

		if cancel:
			refund_amount -= amount
		else:
			refund_amount += amount

		if self.is_excess_amount_refund:
			if not flt(refund_amount):
				self.mark_loan_as_closed()
			elif refund_amount < 0:
				frappe.throw(_("Excess amount refund cannot be more than excess amount paid"))
		elif self.is_security_amount_refund:
			loan_security_deposit = frappe.qb.DocType("Loan Security Deposit")

			if self.refund_amount > flt(security_deposit_available_amount):
				frappe.throw(_("Refund amount cannot be more than available amount"))

			frappe.qb.update(loan_security_deposit).set(
				loan_security_deposit.available_amount, loan_security_deposit.available_amount - amount
			).set(
				loan_security_deposit.refund_amount, loan_security_deposit.refund_amount + amount
			).where(
				loan_security_deposit.loan == self.loan
			).run()

			# if not flt(refund_amount):
			# 	self.mark_loan_as_closed()

		frappe.db.set_value("Loan", self.loan, fieldname, refund_amount)

	def mark_loan_as_closed(self):
		frappe.db.set_value(
			"Loan", self.loan, {"status": "Closed", "closure_date": getdate(self.value_date)}
		)
		schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": self.loan, "docstatus": 1, "status": "Active"}
		)
		if schedule:
			frappe.db.set_value("Loan Repayment Schedule", schedule, "status", "Closed")

	def make_gl_entries(self, cancel=0):
		gl_entries = []
		loan_details = frappe.db.get_value(
			"Loan Product",
			self.loan_product,
			["loan_account", "security_deposit_account", "customer_refund_account"],
			as_dict=1,
		)

		if not loan_details.customer_refund_account:
			frappe.throw(_("Please add customer refund account in Loan Product"))

		if self.is_security_amount_refund:
			debit_account = loan_details.security_deposit_account
			credit_account = self.refund_account
		elif self.is_excess_amount_refund:
			debit_account = loan_details.customer_refund_account
			credit_account = self.refund_account
		else:
			credit_account = self.refund_account
			debit_account = loan_details.customer_refund_account

		gl_entries.append(
			self.get_gl_dict(
				{
					"account": credit_account,
					"against": debit_account,
					"credit": self.refund_amount,
					"credit_in_account_currency": self.refund_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.loan,
					"remarks": _("Against Loan:") + self.loan,
					"cost_center": self.cost_center,
					"posting_date": getdate(self.posting_date),
				}
			)
		)

		gl_entries.append(
			self.get_gl_dict(
				{
					"account": debit_account,
					"against": credit_account,
					"debit": self.refund_amount,
					"debit_in_account_currency": self.refund_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.loan,
					"remarks": _("Against Loan:") + self.loan,
					"cost_center": self.cost_center,
					"posting_date": getdate(self.posting_date),
					"party_type": self.applicant_type,
					"party": self.applicant,
				}
			)
		)

		make_gl_entries(gl_entries, cancel=cancel, merge_entries=False)
