# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import flt


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
		loans = [d.loan for d in self.loans]

		balances = get_balances_based_on_dimensions(
			self.company, self.transfer_date, loans, self.from_branch
		)

		for loan, balance in balances.items():
			self.make_update_journal_entry(loan, balance)

	def on_submit(self):
		self.update_branch()

		if len(self.loans) > 10:
			frappe.enqueue(self.submit_cancel_journal_entries, queue="long")
		else:
			self.submit_cancel_journal_entries()

	def update_branch(self, cancel=0):
		branch_fieldname = frappe.db.get_value(
			"Accounting Dimension", {"document_type": "Branch"}, "fieldname"
		)

		if cancel:
			branch = self.from_branch
		else:
			branch = self.to_branch

		for loan in self.loans:
			frappe.db.set_value("Loan", loan.loan, branch_fieldname, branch)

	def on_cancel(self):
		self.update_branch(cancel=1)
		self.submit_cancel_journal_entries(cancel=1)

	def submit_cancel_journal_entries(self, cancel=0):
		for loan in self.loans:
			je_exists = frappe.db.get_value(
				"Journal Entry", {"loan": loan.loan, "loan_transfer": self.name}, "name"
			)

			if je_exists:
				je_doc = frappe.get_doc("Journal Entry", je_exists)
				if cancel:
					je_doc.cancel()
				else:
					je_doc.submit()

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
			if flt(abs(balance.bal_in_account_currency)) > 0.01:
				account_type = frappe.get_cached_value("Account", balance.account, "account_type")
				party = ""
				party_type = ""

				if account_type in ("Receivable", "Payable"):
					party = balance.party
					party_type = balance.party_type

				je_doc.append(
					"accounts",
					{
						"account": balance.account,
						"debit_in_account_currency": balance.bal_in_account_currency,
						"party_type": party_type,
						"party": party,
						"reference_type": balance.against_voucher_type,
						"reference_name": balance.against_voucher,
						branch_fieldname: self.to_branch,
					},
				)

				je_doc.append(
					"accounts",
					{
						"account": balance.account,
						"credit_in_account_currency": balance.bal_in_account_currency,
						"party_type": party_type,
						"party": party,
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


def get_balances_based_on_dimensions(company, transfer_date, loans, from_branch):
	"""Get balance for dimension-wise pl accounts"""

	qb_dimension_fields = ["cost_center", "finance_book", "project"]
	branch_fieldname = frappe.db.get_value(
		"Accounting Dimension", {"document_type": "Branch"}, "fieldname"
	)

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
		& (gl_entry.posting_date <= transfer_date)
		& (gl_entry.against_voucher_type == "Loan")
		& (gl_entry.against_voucher.isin(loans))
	)

	query = query.where(gl_entry[branch_fieldname] == from_branch)

	query = query.groupby(gl_entry[branch_fieldname])

	query = query.groupby(gl_entry.account)
	query = query.groupby(gl_entry.against_voucher)

	result = query.run(as_dict=1)
	sorted_result = {}

	for entry in result:
		sorted_result.setdefault(entry.against_voucher, []).append(entry)

	return sorted_result
