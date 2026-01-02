from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.utils import loan_accounting_enabled


class LoanController(AccountsController):
	def make_gl_entries(self, *args, **kwargs):
		if not loan_accounting_enabled(self.company):
			return

		return make_gl_entries(*args, **kwargs)
