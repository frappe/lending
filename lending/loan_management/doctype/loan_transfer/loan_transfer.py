# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)


class LoanTransfer(Document):
	def after_insert(self):
		self.get_balances_and_make_journal_entry()

	def validate(self):
		if not self.get("loans"):
			loans = get_loans(self.from_branch, self.applicant)

			if not loans:
				frappe.throw("No loans found for this applicant or branch")

			for loan in loans:
				self.append("loans", {"loan": loan})

		if not self.is_new():
			self.get_balances_and_make_journal_entry()

	def get_balances_and_make_journal_entry(self):
		accounts = get_loan_accounts()
		loans = [d.loan for d in self.loans]

		balances = get_balances_based_on_dimensions(
			self.company, self.transfer_date, accounts, loans, self.from_branch
		)

		for loan, balance in balances.items():
			self.make_update_journal_entry(loan, balance)

	def on_submit(self):
		if len(self.loans) > 10:
			frappe.enqueue(self.submit_journal_entries, queue="long")
		else:
			self.submit_journal_entries()

	def submit_journal_entries(self):
		branch_fieldname = frappe.db.get_value(
			"Accounting Dimension", {"document_type": "Branch"}, "fieldname"
		)

		for loan in self.loans:
			je_exists = frappe.db.get_value(
				"Journal Entry", {"loan": loan.loan, "loan_transfer": self.name}, "name"
			)

			if je_exists:
				je_doc = frappe.get_doc("Journal Entry", je_exists)
				je_doc.submit()
				# frappe.db.set_value("Loan", loan.loan, branch_fieldname, self.to_branch)

	def make_update_journal_entry(self, loan, balances):
		branch_fieldname = frappe.db.get_value(
			"Accounting Dimension", {"document_type": "Branch"}, "fieldname"
		)

		je_exists = frappe.db.get_value(
			"Journal Entry", {"loan": loan, "loan_transfer": self.name}, "name"
		)

		if je_exists:
			je_doc = frappe.get_doc("Journal Entry", je_exists)
			je_doc.set("accounts", [])
		else:
			je_doc = frappe.new_doc("Journal Entry")

		je_doc.posting_date = self.transfer_date
		je_doc.company = self.company
		je_doc.loan_transfer = self.name
		je_doc.loan = loan

		for balance in balances:
			if flt(balance.bal_in_account_currency) > 0.01:
				je_doc.append(
					"accounts",
					{
						"account": balance.account,
						"credit_in_account_currency": balance.bal_in_account_currency,
						"party_type": balance.party_type,
						"party": balance.party,
						"reference_type": balance.against_voucher_type,
						"reference_name": balance.against_voucher,
						branch_fieldname: self.to_branch,
					},
				)

				je_doc.append(
					"accounts",
					{
						"account": balance.account,
						"debit_in_account_currency": balance.bal_in_account_currency,
						"party_type": balance.party_type,
						"party": balance.party,
						"reference_type": balance.against_voucher_type,
						"reference_name": balance.against_voucher,
						branch_fieldname: self.from_branch,
					},
				)

		if je_doc.get("accounts"):
			je_doc.save()


@frappe.whitelist()
def get_loans(branch, applicant=None):
	branch_fieldname = frappe.db.get_value(
		"Accounting Dimension", {"document_type": "Branch"}, "fieldname"
	)

	filters = {branch_fieldname: branch, "docstatus": 1}

	if applicant:
		filters["applicant"] = applicant

	loans = frappe.get_all("Loan", filters=filters, pluck="name")
	return loans


def get_loan_accounts():
	accounts = []
	account_fields = ["loan_account", "interest_income_account", "interest_accrued_account"]

	account_details = frappe.get_all("Loan Product", fields=account_fields)

	accounts = []
	for account in account_details:
		for field in account_fields:
			if account.get(field) not in accounts:
				accounts.append(account.get(field))

	return accounts


def get_balances_based_on_dimensions(company, transfer_date, accounts, loans, from_branch):
	"""Get balance for dimension-wise pl accounts"""

	qb_dimension_fields = ["cost_center", "finance_book", "project"]
	accounting_dimensions = get_accounting_dimensions()

	for dimension in accounting_dimensions:
		qb_dimension_fields.append(dimension)

	qb_dimension_fields.append("account")

	gl_entry = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gl_entry).select(
		gl_entry.account, gl_entry.account_currency, gl_entry.party_type, gl_entry.party
	)

	query = query.select(
		(Sum(gl_entry.debit_in_account_currency) - Sum(gl_entry.credit_in_account_currency)).as_(
			"bal_in_account_currency"
		)
	)

	for dimension in qb_dimension_fields:
		query = query.select(gl_entry[dimension])

	query = query.select(gl_entry.against_voucher, gl_entry.against_voucher_type)

	query = query.where(
		(gl_entry.company == company)
		& (gl_entry.is_cancelled == 0)
		& (gl_entry.account.isin(accounts))
		& (gl_entry.posting_date <= transfer_date)
		& (gl_entry.against_voucher_type == "Loan")
		& (gl_entry.against_voucher.isin(loans))
	)

	for dimension in qb_dimension_fields:
		query = query.groupby(gl_entry[dimension])

	query = query.groupby(gl_entry.account)
	query = query.groupby(gl_entry.against_voucher)

	result = query.run(as_dict=1)
	sorted_result = {}

	for entry in result:
		sorted_result.setdefault(entry.against_voucher, []).append(entry)

	return sorted_result
