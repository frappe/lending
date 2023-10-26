# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	get_pending_principal_amount,
)


class LoanWriteOff(AccountsController):
	def validate(self):
		self.set_missing_values()
		self.validate_write_off_amount()

	def set_missing_values(self):
		if not self.cost_center:
			self.cost_center = erpnext.get_default_cost_center(self.company)

	def validate_write_off_amount(self):
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		loan_details = frappe.get_value(
			"Loan",
			self.loan,
			[
				"total_payment",
				"debit_adjustment_amount",
				"credit_adjustment_amount",
				"refund_amount",
				"total_principal_paid",
				"loan_amount",
				"total_interest_payable",
				"written_off_amount",
				"disbursed_amount",
				"status",
			],
			as_dict=1,
		)

		pending_principal_amount = flt(get_pending_principal_amount(loan_details), precision)

		if self.write_off_amount > pending_principal_amount:
			frappe.throw(_("Write off amount cannot be greater than pending principal amount"))

	def on_submit(self):
		self.update_outstanding_amount()
		self.make_gl_entries()
		self.close_employee_loan()

	def on_cancel(self):
		self.update_outstanding_amount(cancel=1)
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries(cancel=1)
		self.close_employee_loan(cancel=1)

	def update_outstanding_amount(self, cancel=0):
		written_off_amount = frappe.db.get_value("Loan", self.loan, "written_off_amount")

		if cancel:
			written_off_amount -= self.write_off_amount
		else:
			written_off_amount += self.write_off_amount

		frappe.db.set_value("Loan", self.loan, "written_off_amount", written_off_amount)

	def make_gl_entries(self, cancel=0):
		gl_entries = []
		loan_details = frappe.get_doc("Loan", self.loan)

		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.write_off_account,
					"against": loan_details.loan_account,
					"debit": self.write_off_amount,
					"debit_in_account_currency": self.write_off_amount,
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
					"account": loan_details.loan_account,
					"party_type": loan_details.applicant_type,
					"party": loan_details.applicant,
					"against": self.write_off_account,
					"credit": self.write_off_amount,
					"credit_in_account_currency": self.write_off_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.loan,
					"remarks": _("Against Loan:") + self.loan,
					"cost_center": self.cost_center,
					"posting_date": getdate(self.posting_date),
				}
			)
		)

		make_gl_entries(gl_entries, cancel=cancel, merge_entries=False)

	def close_employee_loan(self, cancel=0):
		if not frappe.db.has_column("Loan", "repay_from_salary"):
			return

		loan = frappe.get_value(
			"Loan",
			self.loan,
			[
				"total_payment",
				"total_principal_paid",
				"loan_amount",
				"total_interest_payable",
				"written_off_amount",
				"disbursed_amount",
				"status",
				"is_secured_loan",
				"repay_from_salary",
				"name",
			],
			as_dict=1,
		)

		if loan.is_secured_loan or not loan.repay_from_salary:
			return

		if not cancel:
			pending_principal_amount = get_pending_principal_amount(loan)

			precision = cint(frappe.db.get_default("currency_precision")) or 2

			if flt(pending_principal_amount, precision) <= 0:
				frappe.db.set_value("Loan", loan.name, "status", "Closed")
				frappe.msgprint(_("Loan {0} closed").format(loan.name))
		else:
			frappe.db.set_value("Loan", loan.loan, "status", "Disbursed")
