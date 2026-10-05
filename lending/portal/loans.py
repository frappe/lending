# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from lending.loan_management.doctype.loan.loan import new_loan_disbursement
from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
	calculate_disbursal_amount,
)
from lending.portal import preview
from lending.portal.core import (
	STATUS_LABELS,
	active_schedule_names,
	as_administrator,
	assert_owns,
	chosen_loan,
	get_loans,
	get_portal_customers,
	is_live,
	long_date,
	money,
	next_repayment_for,
	shell_payload,
)

# Risk fields (DPD, NPA classification) are deliberately never selected.
DETAIL_FIELDS = (
	"name",
	"applicant",
	"loan_product",
	"status",
	"loan_amount",
	"disbursed_amount",
	"rate_of_interest",
	"repayment_periods",
	"repayment_frequency",
	"repayment_start_date",
	"monthly_repayment_amount",
	"total_payment",
	"total_amount_paid",
	"total_principal_paid",
	"total_interest_payable",
	"written_off_amount",
)

# Mirrors the statuses the desk offers Create > Loan Disbursement on.
DRAWABLE_STATUSES = ("Sanctioned", "Partially Disbursed", "Active")


@frappe.whitelist()
def get_loan_detail() -> dict:
	if preview.is_preview():
		return preview.loan_detail(frappe.form_dict.get("name"))

	name = frappe.form_dict.get("name") or default_loan()
	if not name:
		return no_loan_payload()

	assert_owns("Loan", name)
	loan = frappe.db.get_value("Loan", name, DETAIL_FIELDS, as_dict=True)

	payload = shell_payload(loan.loan_product, _("Download statement"), [loan])
	payload["crumb"] = loan.loan_product
	payload["head_note"] = "{0} · {1}".format(loan.name, STATUS_LABELS.get(loan.status, loan.status))

	payload.update(
		{
			"product": loan.loan_product,
			"terms": loan_terms(loan),
			"summary_note": _("Key information about your loan."),
			"charges": charge_rows(name),
			"drawdown": drawdown(loan),
			**payoff_figures(name),
		}
	)

	return payload


@frappe.whitelist(methods=["POST"])
def request_disbursement() -> dict:
	"""Raise a draft Loan Disbursement for staff to review; never submitted from here."""
	name = frappe.form_dict.get("name")
	assert_owns("Loan", name)

	# Locked so two concurrent requests cannot both find no draft waiting.
	status = frappe.db.get_value("Loan", name, "status", for_update=True)
	if status not in DRAWABLE_STATUSES:
		frappe.throw(_("This loan is not open for a disbursement."), frappe.ValidationError)

	if pending_disbursement(name):
		frappe.throw(
			_("We already have a disbursement request on this loan. We will be in touch about it."),
			frappe.ValidationError,
		)

	amount = flt(frappe.form_dict.get("amount"))
	available = drawable_amount(name)
	if amount <= 0:
		frappe.throw(_("Please give the amount you need."), frappe.ValidationError)

	if amount > available:
		frappe.throw(
			_("You can ask for up to {0} on this loan.").format(money(available)), frappe.ValidationError
		)

	disbursement = new_loan_disbursement(name, amount, repayment_start_date=next_due_date(name))
	disbursement.insert(ignore_permissions=True)
	disbursement.add_comment("Comment", _("Requested by {0} from the borrower portal.").format(frappe.session.user))

	return {
		"headline": _("Request sent"),
		"message": _("We have your request for {0}. We will be in touch before we pay it out.").format(
			money(amount)
		),
	}


def next_due_date(loan: str):
	# A later tranche joins the running schedule; the loan's own first due date may be past.
	return next_repayment_for(loan).get("payment_date")


def drawdown(loan: dict) -> dict:
	pending = pending_disbursement(loan.name)
	if pending:
		return {
			"loan": loan.name,
			"open": False,
			"available": 0,
			"note": _("A disbursement of {0} is being prepared.").format(money(pending)),
		}

	available = drawable_amount(loan.name) if loan.status in DRAWABLE_STATUSES else 0

	return {
		"loan": loan.name,
		"open": available > 0,
		"available": available,
		"note": _("Up to {0} available to draw.").format(money(available)) if available > 0 else "",
	}


def pending_disbursement(loan: str) -> float:
	return flt(
		frappe.db.get_value("Loan Disbursement", {"against_loan": loan, "docstatus": 0}, "disbursed_amount")
	)


def drawable_amount(loan: str) -> float:
	# Returns a bare 0 instead of a tuple on a security shortfall.
	result = calculate_disbursal_amount(loan)
	return max(flt(result[0] if isinstance(result, tuple) else result), 0)


def default_loan() -> str | None:
	customers = get_portal_customers()
	loans = get_loans(customers) if customers else []
	if not loans:
		return None

	if chosen := chosen_loan(loans):
		return chosen.name

	newest = sorted(loans, key=lambda loan: loan.posting_date, reverse=True)
	live = [loan for loan in newest if is_live(loan)]

	return (live or newest)[0].name


def no_loan_payload() -> dict:
	payload = shell_payload(_("Loan account"), _("Apply for a loan"), [])
	payload.update(
		{
			"product": "",
			"terms": None,
			"summary_note": _("No loan accounts yet"),
			"charges": [],
			"drawdown": {"loan": "", "open": False, "available": 0, "note": ""},
			"payoff_total": money(0),
			"payoff_note": _("Nothing outstanding"),
		}
	)

	return payload


def loan_terms(loan: dict) -> dict:
	written_off = flt(loan.written_off_amount)

	return {
		"sanctioned": money(loan.loan_amount),
		"disbursed": money(loan.disbursed_amount),
		"rate": "{0}%".format(flt(loan.rate_of_interest, 2)),
		"tenure": tenure(loan),
		"instalment": money(instalment(loan)),
		"frequency": _(loan.repayment_frequency or "Monthly"),
		"total": money(loan.total_payment),
		"paid": money(loan.total_amount_paid),
		"next_due": next_due(loan.name),
		"written_off": _("{0} written off").format(money(written_off)) if written_off else "",
	}


def instalment(loan: dict) -> float:
	# Loan's EMI is priced on the full sanction; a partly drawn loan's active schedule is the real one.
	schedules = active_schedule_names([loan.name])
	if schedules:
		return frappe.db.get_value("Loan Repayment Schedule", schedules[0], "monthly_repayment_amount")

	return loan.monthly_repayment_amount


def next_due(loan: str) -> str:
	upcoming = next_repayment_for(loan)
	return long_date(upcoming.payment_date) if upcoming else _("Nothing due")


def tenure(loan: dict) -> str:
	periods = loan.repayment_periods or 0
	if (loan.repayment_frequency or "Monthly") == "Monthly":
		return _("{0} months").format(periods)

	return _("{0} instalments").format(periods)


def charge_rows(loan: str) -> list[dict]:
	rows = frappe.get_all(
		"Loan Disbursement Charge",
		filters={"parent": loan, "parenttype": "Loan"},
		fields=["charge", "amount", "treatment_of_charge"],
		ignore_permissions=True,
	)

	return [
		{
			"label": row.charge,
			"value": money(row.amount),
			"detail": row.treatment_of_charge or "",
		}
		for row in rows
	]


def payoff_figures(loan: str) -> dict:
	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	# calculate_amounts needs Loan read, which Website Users lack; caller already ran assert_owns.
	try:
		with as_administrator():
			payable = flt(calculate_amounts(loan, nowdate(), payment_type="Loan Closure").get("payable_amount"))
	except Exception:
		# Raises on a closed or written-off loan.
		frappe.clear_last_message()
		payable = 0

	return {
		"payoff_total": money(max(payable, 0)),
		"payoff_note": (
			_("As on {0}").format(long_date(nowdate())) if payable > 0 else _("Nothing outstanding")
		),
	}
