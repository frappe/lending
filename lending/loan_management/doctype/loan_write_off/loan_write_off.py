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

		if self.write_off_amount != pending_principal_amount and not self.is_settlement_write_off:
			frappe.throw(_("Write off amount should be equal to pending principal amount"))

	def on_submit(self):
		from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
			create_process_loan_classification,
		)
		from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
			process_daily_loan_demands,
		)

		if not self.is_settlement_write_off:
			process_daily_loan_demands(self.posting_date, loan=self.loan)

		self.process_unbooked_interest()

		if not self.is_settlement_write_off:
			make_loan_waivers(self.loan, self.posting_date)

		self.make_gl_entries()
		self.cancel_suspense_entries()
		write_off_charges(self.loan, self.posting_date, self.company, on_write_off=True)
		self.close_employee_loan()
		self.update_outstanding_amount_and_status()

		create_process_loan_classification(
			posting_date=self.posting_date,
			loan_product=self.loan_product,
			loan=self.loan,
		)

	def process_unbooked_interest(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
		from lending.loan_management.doctype.loan_repayment.loan_repayment import (
			get_last_demand_date,
			get_unbooked_interest,
		)

		last_demand_date = get_last_demand_date(self.loan, self.posting_date)

		unbooked_interest, unbooked_penalty = get_unbooked_interest(
			self.loan, self.posting_date, last_demand_date=last_demand_date
		)
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		if flt(unbooked_interest) > 0:
			create_loan_demand(
				self.loan, self.posting_date, "EMI", "Interest", flt(unbooked_interest, precision)
			)

	def cancel_suspense_entries(self):
		write_off_suspense_entries(
			self.loan, self.loan_product, self.posting_date, self.company, is_write_off=self.is_npa
		)

	def on_cancel(self):
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.cancel_waiver_entries()
		self.make_gl_entries(cancel=1)
		self.close_employee_loan(cancel=1)
		self.update_outstanding_amount_and_status(cancel=1)

	def cancel_waiver_entries(self):
		write_off_count = frappe.db.count("Loan Write Off", {"loan": self.loan, "docstatus": 1})

		if write_off_count >= 1:
			return

		waivers = get_write_off_waivers_for_cancel(self.loan, self.posting_date)

		for waiver in waivers:
			doc = frappe.get_doc("Loan Repayment", waiver)
			doc.flags.ignore_links = True
			doc.cancel()

	def update_outstanding_amount_and_status(self, cancel=0):
		written_off_amount = frappe.db.get_value("Loan", self.loan, "written_off_amount")
		write_off_count = frappe.db.count("Loan Write Off", {"loan": self.loan, "docstatus": 1})

		if cancel:
			written_off_amount -= self.write_off_amount
		else:
			written_off_amount += self.write_off_amount

		update_values = {"written_off_amount": written_off_amount}

		if not (self.is_settlement_write_off or cancel) or write_off_count > 1:
			update_values["status"] = "Written Off"
		elif not self.is_settlement_write_off:
			update_values["status"] = "Disbursed"

		frappe.db.set_value("Loan", self.loan, update_values)

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
		if not self.applicant_type == "Employee":
			return
		opts = [
			"total_payment",
			"total_principal_paid",
			"loan_amount",
			"total_interest_payable",
			"written_off_amount",
			"disbursed_amount",
			"status",
			"is_secured_loan",
			"name",
		]

		if frappe.db.has_column("Loan", "repay_from_salary"):
			opts.append("repay_from_salary")

		loan = frappe.get_value(
			"Loan",
			self.loan,
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


def write_off_suspense_entries(
	loan,
	loan_product,
	posting_date,
	company,
	is_write_off=0,
	interest_amount=0,
	penalty_amount=0,
	additional_interest_amount=0,
	on_payment_allocation=False,
	is_reverse=0,
):
	from lending.loan_management.doctype.loan.loan import make_journal_entry

	is_settled = frappe.db.get_value(
		"Loan Repayment", {"against_loan": loan, "docstatus": 1, "repayment_type": "Full Settlement"}
	)
	if is_settled and not on_payment_allocation:
		is_write_off = 1

	accounts = frappe.db.get_value(
		"Loan Product",
		loan_product,
		[
			"suspense_interest_income",
			"penalty_suspense_account",
			"interest_waiver_account",
			"penalty_waiver_account",
			"interest_income_account",
			"penalty_income_account",
			"additional_interest_suspense",
			"additional_interest_income",
			"additional_interest_waiver",
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
				"account": (
					"in",
					[
						accounts.suspense_interest_income,
						accounts.penalty_suspense_account,
						accounts.additional_interest_suspense,
					],
				),
				"is_cancelled": 0,
				"posting_date": ("<=", posting_date),
			},
			group_by="account",
			as_list=1,
		)
	)

	if amounts.get(accounts.suspense_interest_income, 0) > 0:
		if interest_amount and (
			interest_amount <= amounts.get(accounts.suspense_interest_income) or is_reverse
		):
			amount = interest_amount
		else:
			amount = amounts.get(accounts.suspense_interest_income)

		if not (on_payment_allocation and not interest_amount > 0):
			debit_account = accounts.suspense_interest_income
			credit_account = (
				accounts.interest_waiver_account if is_write_off else accounts.interest_income_account
			)
			make_journal_entry(
				posting_date, company, loan, amount, debit_account, credit_account, is_reverse=is_reverse
			)

	if amounts.get(accounts.penalty_suspense_account, 0) > 0:
		if penalty_amount and (
			penalty_amount <= amounts.get(accounts.penalty_suspense_account) or is_reverse
		):
			amount = penalty_amount
		else:
			amount = amounts.get(accounts.penalty_suspense_account)

		if not (on_payment_allocation and not penalty_amount > 0):
			debit_account = accounts.penalty_suspense_account
			credit_account = (
				accounts.penalty_waiver_account if is_write_off else accounts.penalty_income_account
			)
			make_journal_entry(
				posting_date, company, loan, amount, debit_account, credit_account, is_reverse=is_reverse
			)

	if amounts.get(accounts.additional_interest_suspense, 0) > 0:
		if additional_interest_amount and (
			additional_interest_amount <= amounts.get(accounts.additional_interest_suspense) or is_reverse
		):
			amount = additional_interest_amount
		else:
			amount = amounts.get(accounts.additional_interest_suspense)

		if not (on_payment_allocation and not additional_interest_amount > 0):
			debit_account = accounts.additional_interest_suspense
			credit_account = (
				accounts.additional_interest_waiver if is_write_off else accounts.additional_interest_income
			)
			make_journal_entry(
				posting_date, company, loan, amount, debit_account, credit_account, is_reverse=is_reverse
			)


def write_off_charges(
	loan,
	posting_date,
	company,
	amount_details=None,
	on_write_off=False,
	base_amount_map=None,
	is_reverse=0,
):
	from lending.loan_management.doctype.loan.loan import make_journal_entry

	loan_product = frappe.db.get_value("Loan", loan, "loan_product")

	if on_write_off:
		account_fieldname = "write_off_account"
	else:
		account_fieldname = "income_account"

	suspense_account_map = frappe._dict(
		frappe.db.get_all(
			"Loan Charges",
			{"parent": loan_product},
			[
				"suspense_account",
				account_fieldname,
			],
			as_list=1,
		)
	)

	suspense_accounts = [key for key, value in suspense_account_map.items()]

	amounts = frappe._dict(
		frappe.db.get_all(
			"GL Entry",
			fields=["account", "sum(credit) - sum(debit) as amount"],
			filters={
				"against_voucher_type": "Loan",
				"against_voucher": loan,
				"account": ("in", suspense_accounts),
				"is_cancelled": 0,
				"posting_date": ("<=", posting_date),
			},
			group_by="account",
			as_list=1,
		)
	)

	for account, amount in amounts.items():
		if amount > 0:
			if amount_details:
				partial_amount = amount_details.get(account)
				if partial_amount and partial_amount <= amount:
					amount = partial_amount
				elif amount_details and not partial_amount:
					continue

			if base_amount_map and on_write_off:
				waiver_account = suspense_account_map.get(account)
				base_amount = base_amount_map.get(waiver_account, 0)

				if base_amount > 0:
					income_account = frappe.db.get_value(
						"Loan Charges", {"parent": loan_product, "suspense_account": account}, "income_account"
					)
					income_amount = amount - base_amount
					make_journal_entry(
						posting_date,
						company,
						loan,
						income_amount,
						waiver_account,
						income_account,
						is_reverse=is_reverse,
					)

			waiver_account = suspense_account_map.get(account)
			make_journal_entry(
				posting_date, company, loan, amount, account, waiver_account, is_reverse=is_reverse
			)


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


def get_write_off_waivers_for_cancel(loan_name, posting_date):
	return frappe.db.get_all(
		"Loan Repayment",
		filters={
			"against_loan": loan_name,
			"posting_date": ("<=", posting_date),
			"docstatus": 1,
			"is_write_off_waiver": 1,
		},
		pluck="name",
	)


def get_write_off_waivers(loan_name, posting_date):
	return frappe._dict(
		frappe.db.get_all(
			"Loan Repayment",
			filters={
				"against_loan": loan_name,
				"posting_date": ("<=", posting_date),
				"docstatus": 1,
				"is_write_off_waiver": 1,
			},
			fields=["repayment_type", "sum(amount_paid) as amount"],
			group_by="repayment_type",
			as_list=1,
		)
	)


def get_write_off_recovery_details(loan_name, posting_date, settlement_date=None):

	filters = {"against_loan": loan_name, "posting_date": ("<=", posting_date), "docstatus": 1}

	if settlement_date:
		filters["posting_date"] = (">", settlement_date)
	else:
		filters["repayment_type"] = ("in", ["Write Off Recovery", "Write Off Settlement"])

	write_of_recovery_details = frappe.db.get_value(
		"Loan Repayment",
		filters,
		[
			"sum(total_penalty_paid) as total_penalty",
			"sum(total_interest_paid) as total_interest",
			"sum(total_charges_paid) as total_charges",
			"sum(principal_amount_paid) as total_principal",
		],
		as_dict=1,
	)

	return write_of_recovery_details or {}


def get_accrued_interest_for_write_off_recovery(loan_name, posting_date):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		get_accrued_interest,
		get_last_demand_date,
	)

	last_interest_demand_date = get_last_demand_date(loan_name, posting_date)
	last_penalty_demand_date = get_last_demand_date(loan_name, posting_date, demand_subtype="Penalty")

	accrued_interest = get_accrued_interest(
		loan_name, posting_date, last_demand_date=last_interest_demand_date
	)
	accrued_penalty = get_accrued_interest(
		loan_name,
		posting_date,
		interest_type="Penal Interest",
		last_demand_date=last_penalty_demand_date,
	)

	return accrued_interest, accrued_penalty
