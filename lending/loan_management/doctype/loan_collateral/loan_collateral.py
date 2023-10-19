# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import itertools

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from lending.loan_management.doctype.loan_collateral_values_log.loan_collateral_values_log import (
	create_loan_collateral_values_log,
)


class LoanCollateral(Document):
	def validate(self):
		self.set_available_collateral_value()

	def set_available_collateral_value(self):
		self.available_collateral_value = self.collateral_value


def update_loan_collaterals_values(
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

	if not frappe.db.get_value("Loan", loan, "is_secured_loan"):
		return

	utilized_value_increased = (
		True
		if (disbursement and not on_trigger_doc_cancel) or (repayment and on_trigger_doc_cancel)
		else False
	)

	sorted_loan_collaterals = _get_sorted_loan_collaterals_to_update_values(
		loan, utilized_value_increased
	)

	_update_loan_collaterals_values(
		sorted_loan_collaterals,
		amount,
		utilized_value_increased,
		trigger_doctype,
		trigger_doc,
		on_trigger_doc_cancel,
	)


def _get_sorted_loan_collaterals_to_update_values(loan, utilized_value_increased):
	loan_collaterals_w_ratio = []

	for loan_security_pledge in frappe.db.get_all(
		"Loan Security Pledge", {"loan": loan}, pluck="name"
	):
		loan_collaterals = frappe.db.get_all(
			"Loan Collateral Assignment Loan Collateral",
			{"parent": loan_security_pledge},
			pluck="loan_collateral",
		)

		for loan_collateral in loan_collaterals:
			(
				collateral_value,
				available_collateral_value,
				utilized_collateral_value,
			) = frappe.db.get_value(
				"Loan Collateral",
				loan_collateral,
				[
					"collateral_value",
					"available_collateral_value",
					"utilized_collateral_value",
				],
			)

			utilized_to_original_value_ratio = flt(utilized_collateral_value / collateral_value)

			loan_collaterals_w_ratio.append(
				frappe._dict(
					{
						"loan_collateral": loan_collateral,
						"collateral_value": collateral_value,
						"utilized_collateral_value": utilized_collateral_value,
						"available_collateral_value": available_collateral_value,
						"ratio": utilized_to_original_value_ratio,
					}
				)
			)

	sorted_loan_collaterals = sorted(
		loan_collaterals_w_ratio,
		key=lambda k: k["ratio"],
		reverse=utilized_value_increased,
	)

	return sorted_loan_collaterals


def _update_loan_collaterals_values(
	sorted_loan_collaterals,
	amount,
	utilized_value_increased,
	trigger_doctype,
	trigger_doc,
	on_trigger_doc_cancel,
):
	for loan_collateral in sorted_loan_collaterals:
		if amount <= 0:
			break

		if utilized_value_increased:
			if loan_collateral.utilized_collateral_value + amount > loan_collateral.collateral_value:
				new_utilized_collateral_value = loan_collateral.collateral_value
				new_available_collateral_value = 0
				amount = amount + loan_collateral.utilized_collateral_value - loan_collateral.collateral_value
			else:
				new_utilized_collateral_value = loan_collateral.utilized_collateral_value + amount
				new_available_collateral_value = loan_collateral.available_collateral_value - amount
				amount = 0
		else:
			if loan_collateral.available_collateral_value + amount > loan_collateral.collateral_value:
				new_available_collateral_value = loan_collateral.collateral_value
				new_utilized_collateral_value = 0
				amount = amount + loan_collateral.available_collateral_value - loan_collateral.collateral_value
			else:
				new_utilized_collateral_value = loan_collateral.utilized_collateral_value - amount
				new_available_collateral_value = loan_collateral.available_collateral_value + amount
				amount = 0

		frappe.db.set_value(
			"Loan Collateral",
			loan_collateral.loan_collateral,
			{
				"utilized_collateral_value": new_utilized_collateral_value,
				"available_collateral_value": new_available_collateral_value,
			},
		)

		create_loan_collateral_values_log(
			loan_collateral=loan_collateral.loan_collateral,
			trigger_doctype=trigger_doctype,
			trigger_document=trigger_doc,
			on_trigger_doc_cancel=on_trigger_doc_cancel,
			new_available_collateral_value=new_available_collateral_value,
			new_utilized_collateral_value=new_utilized_collateral_value,
			previous_available_collateral_value=loan_collateral.available_collateral_value,
			previous_utilized_collateral_value=loan_collateral.utilized_collateral_value,
		)


@frappe.whitelist()
def release_loan_collateral(loan_collateral):
	active_loan_collaterals = get_active_loan_collaterals(loan_collateral)

	if active_loan_collaterals:
		msg = _("Loan Collateral {0} is linked with active loans:").format(frappe.bold(loan_collateral))
		for loan_and_pledge in active_loan_collaterals:
			msg += "<br><br>"
			msg += _("Loan {0} through Loan Security Pledge {1}").format(
				frappe.bold(loan_and_pledge.loan), frappe.bold(loan_and_pledge.pledge)
			)
		frappe.throw(msg, title=_("Loan Collateral cannot be released"))
	else:
		frappe.db.set_value(
			"Loan Collateral", loan_collateral, {"status": "Released", "released_date": nowdate()}
		)


def get_active_loan_collaterals(loan_collateral):
	active_loan_collaterals = []

	lcalcs = frappe.db.sql(
		"""
		SELECT lp.loan, lp.name as pledge
		FROM `tabLoan Security Pledge` lp, `tabLoan Collateral Assignment Loan Collateral` p
		WHERE p.loan_collateral = %s
		AND p.parent = lp.name
		AND lp.status = 'Pledged'
		""",
		(loan_collateral),
		as_dict=True,
	)

	lcdcs = frappe.db.sql(
		"""
		SELECT up.loan
		FROM `tabLoan Security Unpledge` up, `tabLoan Collateral Deassignment Loan Collateral` u
		WHERE u.loan_collateral = %s
		AND u.parent = up.name
		AND up.status = 'Approved'
		""",
		(loan_collateral),
		as_list=True,
	)
	lcdcs = list(itertools.chain(*lcdcs))

	for loan_and_pledge in lcalcs:
		if loan_and_pledge.loan not in lcdcs:
			active_loan_collaterals.append(loan_and_pledge)

	return active_loan_collaterals


def check_loan_collaterals_availability(loan, amount=None):
	loan_amount, is_secured_loan = frappe.db.get_value(
		"Loan", loan, ["loan_amount", "is_secured_loan"]
	)

	if not is_secured_loan:
		return

	amount = amount or loan_amount

	total_available_collateral_value = 0

	loan_security_pledges = frappe.db.get_all(
		"Loan Security Pledge", {"loan": loan, "collateral_type": "Loan Collateral"}, pluck="name"
	)

	if not loan_security_pledges:
		return

	for loan_security_pledge in loan_security_pledges:
		loan_collaterals = frappe.db.get_all(
			"Loan Collateral Assignment Loan Collateral",
			{"parent": loan_security_pledge},
			pluck="loan_collateral",
		)
		for loan_collateral in loan_collaterals:
			total_available_collateral_value += frappe.db.get_value(
				"Loan Collateral", loan_collateral, "available_collateral_value"
			)

	if total_available_collateral_value < amount:
		frappe.throw(
			_("Loan Collaterals worth {0} needed more to book the loan.").format(
				frappe.bold(amount - total_available_collateral_value),
			)
		)


@frappe.whitelist()
def get_pending_deassignment_collaterals(loan):
	assignment_collaterals = frappe.db.sql(
		"""
		SELECT lcalc.loan_collateral
		FROM `tabLoan Security Pledge` lsp, `tabLoan Collateral Assignment Loan Collateral` lcalc
		WHERE lsp.loan = %s
		AND lcalc.parent = lsp.name
		""",
		(loan),
		as_list=True,
	)
	assignment_collaterals = list(itertools.chain(*assignment_collaterals))

	deassignment_collaterals = frappe.db.sql(
		"""
		SELECT lcdlc.loan_collateral
		FROM `tabLoan Security Unpledge` lsu, `tabLoan Collateral Deassignment Loan Collateral` lcdlc
		WHERE lsu.loan = %s
		AND lcdlc.parent = lsu.name
		""",
		(loan),
		as_list=True,
	)
	deassignment_collaterals = list(itertools.chain(*deassignment_collaterals))

	return list(set(assignment_collaterals) - set(deassignment_collaterals))
