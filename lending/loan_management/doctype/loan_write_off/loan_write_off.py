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

		if not self.write_off_account:
			self.write_off_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "write_off_account"
			)

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

		if not self.write_off_amount:
			self.write_off_amount = pending_principal_amount

		if self.write_off_amount != pending_principal_amount:
			frappe.throw(_("Write off amount should be equal to pending principal amount"))

	def on_submit(self):
		self.update_outstanding_amount_and_status()
		make_loan_waivers(self.loan, self.posting_date)
		self.make_gl_entries()
		self.cancel_suspense_entries()
		self.close_employee_loan()

	def cancel_suspense_entries(self):
		if not self.is_npa:
			cancel_suspense_entries(self.loan, self.loan_product, self.posting_date)
		else:
			write_off_suspense_entries(self.loan, self.loan_product, self.posting_date, self.company)

	def on_cancel(self):
		self.update_outstanding_amount_and_status(cancel=1)
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries(cancel=1)
		self.close_employee_loan(cancel=1)

	def update_outstanding_amount_and_status(self, cancel=0):
		written_off_amount = frappe.db.get_value("Loan", self.loan, "written_off_amount")

		if cancel:
			written_off_amount -= self.write_off_amount
		else:
			written_off_amount += self.write_off_amount

		frappe.db.set_value(
			"Loan", self.loan, {"written_off_amount": written_off_amount, "status": "Written Off"}
		)

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


def make_loan_waivers(loan, posting_date):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
	from lending.loan_management.doctype.loan_restructure.loan_restructure import (
		create_loan_repayment,
	)

	amounts = calculate_amounts(loan, posting_date)
	if amounts.get("penalty_amount") > 0:
		create_loan_repayment(
			loan,
			posting_date,
			"Penalty Waiver",
			amounts.get("penalty_amount"),
			is_write_off_waiver=1,
		)

	if amounts.get("interest_amount") > 0:
		create_loan_repayment(
			loan,
			posting_date,
			"Interest Waiver",
			amounts.get("interest_amount"),
			is_write_off_waiver=1,
		)

	if amounts.get("total_charges_payable") > 0:
		create_loan_repayment(
			loan,
			posting_date,
			"Charges Waiver",
			amounts.get("total_charges_payable"),
			is_write_off_waiver=1,
		)


def write_off_suspense_entries(loan, loan_product, posting_date, company):
	from lending.loan_management.doctype.loan.loan import make_journal_entry

	accounts = frappe.db.get_value(
		"Loan Product",
		loan_product,
		[
			"suspense_interest_income",
			"penalty_suspense_account",
			"interest_waiver_account",
			"penalty_waiver_account",
		],
		as_dict=1,
	)

	amounts = frappe._dict(
		frappe.db.get_all(
			"GL Entry",
			fields=["account", "sum(credit) - sum(debit) as amount"],
			filters={
				"against_voucher_type": "Loan",
				"against_voucher": loan,
				"account": ("in", [accounts.suspense_interest_income, accounts.penalty_suspense_account]),
				"is_cancelled": 0,
			},
			as_list=1,
		)
	)

	if amounts.get(accounts.suspense_interest_income, 0) > 0:
		amount = amounts.get(accounts.suspense_interest_income)
		debit_account = accounts.suspense_interest_income
		credit_account = accounts.interest_waiver_account
		make_journal_entry(posting_date, company, loan, amount, debit_account, credit_account)

	if amounts.get(accounts.penalty_suspense_account, 0) > 0:
		debit_account = accounts.suspense_interest_income
		credit_account = accounts.interest_waiver_account
		make_journal_entry(posting_date, company, loan, amount, debit_account, credit_account)


def cancel_suspense_entries(loan, loan_product, posting_date):
	journal_entries = get_suspense_entries(loan, loan_product)

	for je in journal_entries:
		je_doc = frappe.get_doc("Journal Entry", je)
		frappe.form_dict["posting_date"] = posting_date
		je_doc.cancel()


def get_suspense_entries(loan, loan_product):
	suspense_accounts = frappe.db.get_value(
		"Loan Product", loan_product, ["suspense_interest_income", "penalty_suspense_account"]
	)

	journal_entries = frappe.db.get_all(
		"Journal Entry Account",
		filters={
			"account": ("in", suspense_accounts),
			"docstatus": 1,
			"reference_type": "Loan",
			"reference_name": loan,
		},
		pluck="parent",
	)

	return journal_entries
