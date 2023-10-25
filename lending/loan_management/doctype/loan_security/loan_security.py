# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import itertools

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate


class LoanSecurity(Document):
	pass


@frappe.whitelist()
def release_loan_security(loan_security):
	active_loans_and_lsa = get_active_loan_securities(loan_security)

	if active_loans_and_lsa:
		msg = _("Loan Security {0} is linked with active loans:").format(frappe.bold(loan_security))
		for loan_and_lsa in active_loans_and_lsa:
			msg += "<br><br>"
			msg += _("Loan {0} through Loan Security Assignment {1}").format(
				frappe.bold(loan_and_lsa.loan), frappe.bold(loan_and_lsa.lsa)
			)
		frappe.throw(msg, title=_("Loan Security cannot be released"))
	else:
		frappe.db.set_value(
			"Loan Security", loan_security, {"status": "Released", "released_date": nowdate()}
		)


def get_active_loan_securities(loan_security):
	active_loans_and_lsa = []

	all_loans_and_lsa = frappe.db.sql(
		"""
		SELECT lsald.loan, lsa.name as lsa
		FROM `tabLoan Security Assignment` lsa, `tabPledge` p, `tabLoan Security Assignment Loan Detail` lsald
		WHERE p.loan_security = %s
		AND p.parent = lsa.name
		AND lsald.parent = lsa.name
		AND lsa.status = 'Pledged'
		""",
		(loan_security),
		as_dict=True,
	)

	loans_with_security_unpledged = frappe.db.sql(
		"""
		SELECT lsr.loan
		FROM `tabLoan Security Release` lsr, `tabUnpledge` u
		WHERE u.loan_security = %s
		AND u.parent = lsr.name
		AND lsr.status = 'Approved'
		""",
		(loan_security),
		as_list=True,
	)
	loans_with_security_unpledged = list(itertools.chain(*loans_with_security_unpledged))

	for loan_and_lsa in all_loans_and_lsa:
		if loan_and_lsa.loan not in loans_with_security_unpledged:
			active_loans_and_lsa.append(loan_and_lsa)

	return active_loans_and_lsa
