# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import itertools

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from lending.loan_management.doctype.loan_security_utilized_and_available_value_log.loan_security_utilized_and_available_value_log import (
	create_loan_security_utilized_and_available_value_log,
)


class LoanSecurity(Document):
	def validate(self):
		self.set_missing_values()

	def set_missing_values(self):
		if self.quantifiable:
			self.original_security_value = flt(self.quantity * self.original_security_price)
		else:
			self.quantity = 1
			self.original_security_price = self.original_security_value

		original_post_haircut_security_value = flt(
			self.original_security_value - (self.original_security_value * self.haircut / 100)
		)
		self.original_post_haircut_security_value = original_post_haircut_security_value
		self.available_security_value = original_post_haircut_security_value


def update_utilized_loan_securities_values(
	loan,
	amount,
	trigger_doctype,
	trigger_doc,
	disbursement=False,
	repayment=False,
	on_trigger_doc_cancel=0,
):
	if (disbursement and repayment) or (not disbursement and not repayment):
		frappe.throw(_("The action needs to be either disbursement or repayment"))

	if frappe.db.get_value("Loan", loan, "loan_security_preference") == "Unsecured":
		return

	loan_securities_w_ratio = []

	for loan_security_pledge in frappe.db.get_all(
		"Loan Security Pledge", {"loan": loan}, pluck="name"
	):
		loan_securities = frappe.db.get_all(
			"Pledge", {"parent": loan_security_pledge}, pluck="loan_security"
		)

		for loan_security in loan_securities:
			(
				utilized_security_value,
				original_post_haircut_security_value,
				available_security_value,
			) = frappe.db.get_value(
				"Loan Security",
				loan_security,
				[
					"utilized_security_value",
					"original_post_haircut_security_value",
					"available_security_value",
				],
			)
			utilized_to_original_security_ratio = flt(
				utilized_security_value / original_post_haircut_security_value
			)
			loan_securities_w_ratio.append(
				frappe._dict(
					{
						"loan_security": loan_security,
						"utilized_security_value": utilized_security_value,
						"available_security_value": available_security_value,
						"ratio": utilized_to_original_security_ratio,
					}
				)
			)

	utilized_value_increased = (
		True
		if (disbursement and not on_trigger_doc_cancel) or (repayment and on_trigger_doc_cancel)
		else False
	)

	sorted_loan_securities_w_ratio = sorted(
		loan_securities_w_ratio,
		key=lambda k: k["ratio"],
		reverse=utilized_value_increased,
	)

	for loan_security in sorted_loan_securities_w_ratio:
		if amount <= 0:
			break

		if utilized_value_increased:
			if loan_security.utilized_security_value + amount > loan_security.available_security_value:
				new_utilized_security_value = loan_security.available_security_value
				new_available_security_value = 0
				amount = (
					amount - loan_security.available_security_value + loan_security.utilized_security_value
				)
			else:
				new_utilized_security_value = loan_security.utilized_security_value + amount
				new_available_security_value = loan_security.available_security_value - amount
				amount = 0
		else:
			if loan_security.utilized_security_value >= amount:
				new_utilized_security_value = loan_security.utilized_security_value - amount
				new_available_security_value = loan_security.available_security_value + amount
				amount = 0
			else:
				new_utilized_security_value = 0
				new_available_security_value = (
					loan_security.available_security_value + new_utilized_security_value
				)
				amount = amount - loan_security.utilized_security_value

		frappe.db.set_value(
			"Loan Security",
			loan_security.loan_security,
			{
				"utilized_security_value": new_utilized_security_value,
				"available_security_value": new_available_security_value,
			},
		)

		create_loan_security_utilized_and_available_value_log(
			loan_security=loan_security.loan_security,
			trigger_doctype=trigger_doctype,
			trigger_document=trigger_doc,
			on_trigger_doc_cancel=on_trigger_doc_cancel,
			new_available_security_value=new_available_security_value,
			new_utilized_security_value=new_utilized_security_value,
			previous_available_security_value=loan_security.available_security_value,
			previous_utilized_security_value=loan_security.utilized_security_value,
		)


def get_active_pledges_linked_to_loan_security(loan_security):
	active_pledges = []

	pledges = frappe.db.sql(
		"""
		SELECT lp.loan, lp.name as pledge
		FROM `tabLoan Security Pledge` lp, `tabPledge`p
		WHERE p.loan_security = %s
		AND p.parent = lp.name
		AND lp.status = 'Pledged'
		""",
		(loan_security),
		as_dict=True,
	)

	unpledges = frappe.db.sql(
		"""
		SELECT up.loan
		FROM `tabLoan Security Unpledge` up, `tabUnpledge` u
		WHERE u.loan_security = %s
		AND u.parent = up.name
		AND up.status = 'Approved'
		""",
		(loan_security),
		as_list=True,
	)
	unpledges = list(itertools.chain(*unpledges))

	for loan_and_pledge in pledges:
		if loan_and_pledge.loan not in unpledges:
			active_pledges.append(loan_and_pledge)

	return active_pledges


@frappe.whitelist()
def release_loan_security(loan_security):
	active_pledges = get_active_pledges_linked_to_loan_security(loan_security)

	if active_pledges:
		msg = _("Loan Security {0} is still linked with active loans:").format(
			frappe.bold(loan_security)
		)
		for loan_and_pledge in active_pledges:
			msg += "<br><br>"
			msg += _("Loan {0} through Loan Security Pledge {1}").format(
				frappe.bold(loan_and_pledge.loan), frappe.bold(loan_and_pledge.pledge)
			)
		frappe.throw(msg, title=_("Security cannot be released"))
	else:
		frappe.db.set_value(
			"Loan Security", loan_security, {"status": "Released", "released_at": now_datetime()}
		)
