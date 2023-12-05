# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import cint

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController


class LoanDemand(AccountsController):
	def validate(self):
		pass

	def on_submit(self):
		self.make_gl_entries()
		self.update_repayment_schedule()

	def update_repayment_schedule(self, cancel=0):
		if self.repayment_schedule_detail:
			frappe.db.set_value(
				"Repayment Schedule", self.repayment_schedule_detail, "demand_generated", cint(not cancel)
			)

	def on_cancel(self):
		self.make_gl_entries(cancel=1)
		self.update_repayment_schedule(cancel=1)

	def make_gl_entries(self, cancel=0):
		gl_entries = []

		if self.demand_subtype == "Principal":
			return

		if self.demand_subtype == "Interest":
			accrual_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "interest_accrued_account"
			)
			receivable_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "interest_receivable_account"
			)
		elif self.demand_subtype == "Penalty":
			accrual_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "penalty_accrued_account"
			)
			receivable_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "penalty_receivable_account"
			)

		gl_entries.append(
			self.get_gl_dict(
				{
					"posting_date": self.demand_date,
					"account": receivable_account,
					"against": self.loan,
					"debit": self.demand_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.loan,
					"party_type": self.applicant_type,
					"party": self.applicant,
				}
			)
		)

		gl_entries.append(
			self.get_gl_dict(
				{
					"posting_date": self.demand_date,
					"account": accrual_account,
					"against": receivable_account,
					"credit": self.demand_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.loan,
				}
			)
		)

		make_gl_entries(gl_entries, cancel=cancel, adv_adj=0)
