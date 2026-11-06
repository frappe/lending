# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from lending.portal import preview
from lending.portal.core import (
	CHOSEN_LOAN_KEY,
	chosen_loan,
	get_loans,
	get_portal_customers,
	present_loan,
	shell_payload,
)


@frappe.whitelist()
def get_accounts_page() -> dict:
	customers = get_portal_customers()
	loans = get_loans(customers) if customers else []
	chosen = chosen_loan(loans)

	payload = shell_payload(_("Choose an account"), "", [chosen] if chosen else loans)
	payload["head_note"] = _("Pick the loan account you want to see.")
	payload["accounts"] = [
		dict(
			present_loan(loan, len(customers) > 1),
			chosen=bool(chosen) and loan.name == chosen.name,
		)
		for loan in loans
	]
	payload["accounts_note"] = (
		_("1 account") if len(loans) == 1 else _("{0} accounts").format(len(loans))
	)

	return payload


@frappe.whitelist(methods=["POST"])
def choose_account(name: str) -> dict:
	preview.refuse_writes()
	customers = get_portal_customers()
	loans = get_loans(customers) if customers else []
	if not name or name not in [loan.name for loan in loans]:
		raise frappe.PermissionError(_("Not permitted"))

	frappe.defaults.set_user_default(CHOSEN_LOAN_KEY, name)

	return {"url": "/borrower-portal/overview"}
