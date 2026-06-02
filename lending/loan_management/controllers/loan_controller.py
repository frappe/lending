import frappe

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.utils import loan_accounting_enabled


class LoanController(AccountsController):
	def make_gl_entries(self, *args, **kwargs):
		if not loan_accounting_enabled(self.company):
			return

		loan_doctypes = {
			"Loan Disbursement",
			"Loan Demand",
			"Loan Interest Accrual",
			"Loan Repayment",
		}

		if self.doctype in loan_doctypes and (
			(self.meta.has_field("is_imported") and self.get("is_imported"))
			or getattr(frappe.flags, "in_import", False)
			or getattr(self.flags, "in_import", False)
		):
			return

		return make_gl_entries(*args, **kwargs)
