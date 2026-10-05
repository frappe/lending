# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A made-up borrower for the theme preview in Lending Settings, so no real account is shown."""

from urllib.parse import parse_qs, urlparse

import frappe
from frappe import _
from frappe.utils import add_days, flt, formatdate, getdate, nowdate

from lending.portal.core import (
	STATUS_LABELS,
	STATUS_TONES,
	build_summary,
	decorate_activity,
	decorate_timeline,
	event,
	labels,
	latest,
	loan_url,
	long_date,
	money,
	name_once,
	next_action,
	one_loan_note,
	one_loan_url,
	outstanding_of,
	shell_payload,
	short_date,
	undrawn_of,
)
from lending.portal.theme import PORTAL_PATH

# On the URL of the Lending Settings form's preview frame, so the frame's API calls carry it as
# their Referer. Not a cookie: that reached every tab, and outlived the form it came from.
PARAM = "lending_preview"

HOLDER = "Priya Sharma"

PERSONAL = "LN-PREVIEW-0001"
HOME = "LN-PREVIEW-0002"


def is_preview() -> bool:
	request = getattr(frappe.local, "request", None)
	if not request:
		return False

	page = urlparse(request.headers.get("Referer") or "")
	if page.netloc != request.host or not page.path.startswith(PORTAL_PATH + "/"):
		return False

	# The page's own query, not the whole string: a login redirect nests the flag in redirect-to.
	if parse_qs(page.query).get(PARAM) != ["1"]:
		return False

	# The write check keeps a borrower who forges the Referer on their own data.
	return frappe.has_permission("Lending Settings", "write")


def loans() -> list[frappe._dict]:
	today = getdate(nowdate())

	return [
		frappe._dict(
			name=PERSONAL,
			loan_product="Personal Loan",
			status="Active",
			posting_date=add_days(today, -270),
			loan_amount=500000,
			disbursed_amount=500000,
			total_principal_paid=118400,
			total_amount_paid=148392,
			total_payment=593568,
			rate_of_interest=11.5,
			repayment_periods=36,
			repayment_frequency="Monthly",
			monthly_repayment_amount=16488,
			first_due=add_days(today, 5),
		),
		frappe._dict(
			name=HOME,
			loan_product="Home Loan",
			status="Partially Disbursed",
			posting_date=add_days(today, -120),
			loan_amount=2500000,
			disbursed_amount=1500000,
			total_principal_paid=21600,
			total_amount_paid=88372,
			total_payment=5302320,
			rate_of_interest=8.75,
			repayment_periods=240,
			repayment_frequency="Monthly",
			monthly_repayment_amount=22093,
			first_due=add_days(today, 12),
		),
	]


def instalment(loan: dict) -> float:
	# The home loan pays on its drawn share until the rest is disbursed.
	return round(flt(loan.monthly_repayment_amount) * flt(loan.disbursed_amount) / flt(loan.loan_amount))


def due_dates(loan: dict, count: int) -> list:
	return [add_days(loan.first_due, 30 * month) for month in range(count)]


def schedule(only: dict | None = None) -> list[dict]:
	rows = []
	for loan in [only] if only else loans():
		amount = instalment(loan)
		interest = round(outstanding_of(loan) * loan.rate_of_interest / 1200)
		for day in due_dates(loan, 2):
			rows.append((day, loan, amount, interest))

	rows.sort(key=lambda row: row[0])

	return name_once(
		[
			{
				"date": short_date(day),
				"day": formatdate(day, "dd"),
				"month": formatdate(day, "MMM"),
				"year": formatdate(day, "yyyy"),
				"product": loan.loan_product,
				"detail": _("Principal {0} · Interest {1}").format(
					money(amount - interest), money(interest)
				),
				"principal": _("Principal {0}").format(money(amount - interest)),
				"interest": _("Interest {0}").format(money(interest)),
				"amount": money(amount),
				"url": loan_url(loan.name),
			}
			for day, loan, amount, interest in rows[:4]
		]
	)


def money_events() -> list[dict]:
	events = []
	for loan in loans():
		url = loan_url(loan.name)
		disbursed = money(loan.disbursed_amount)
		events.append(
			event(
				"disbursed",
				add_days(loan.posting_date, 3),
				_("Loan amount received"),
				disbursed,
				loan.loan_product,
				url,
				amount=disbursed,
			)
		)
		paid = money(instalment(loan))
		for day in due_dates(loan, 2):
			day = add_days(day, -60)
			events.append(
				event("repaid", day, _("Payment made"), paid, loan.loan_product, url, amount=paid)
			)

	return events


def applications() -> list[dict]:
	started = add_days(nowdate(), -4)

	return [
		{
			"name": "APP-PREVIEW-0001",
			"url": "/borrower-portal/applications",
			"loan_url": "",
			"product": "Vehicle Loan",
			"reference": "APP-PREVIEW-0001 · initiated {0}".format(long_date(started)),
			"initiated": _("Initiated on {0}").format(long_date(started)),
			"initiated_date": short_date(started),
			"stage": _("Action required"),
			"stage_tone": "warn",
			"needs_borrower": True,
			"amount": money(850000),
			"note": _("Submit to start the review · {0} documents attached").format(2),
		}
	]


def present_loan(loan: dict, next_row: dict) -> dict:
	undrawn = undrawn_of(loan)

	return {
		"name": loan.name,
		"url": loan_url(loan.name),
		"product": loan.loan_product,
		"terms": "{0} · {1}% p.a. · {2} {3}".format(
			loan.name, flt(loan.rate_of_interest, 2), loan.repayment_periods, loan.repayment_frequency.lower()
		),
		"status_label": STATUS_LABELS[loan.status],
		"tone": STATUS_TONES.get(loan.status, ""),
		"customer": "",
		"next_date": next_row["date"],
		"next_amount": next_row["amount"],
		"next_line": _("Next due {0} · {1}").format(next_row["date"], next_row["amount"]),
		"outstanding": money(outstanding_of(loan)),
		"against": (
			_("{0} undrawn").format(money(undrawn)) if undrawn else _("of {0}").format(money(loan.loan_amount))
		),
		"closed_note": "",
	}


def as_holder(payload: dict) -> dict:
	payload.update(
		{
			"holder_name": HOLDER,
			"initials": "PS",
			"head_note": _("{0} · figures as on {1}").format(HOLDER, long_date(nowdate())),
			"can_switch": False,
		}
	)

	return payload


def dashboard() -> dict:
	all_loans = loans()
	rows = schedule()
	pending = applications()
	started = event(
		"created",
		add_days(nowdate(), -4),
		_("Application started"),
		_("You started a new loan application."),
		"Vehicle Loan",
		pending[0]["url"],
		tone="",
	)
	activity = decorate_timeline(latest(money_events() + [started], 5))
	accounts = [present_loan(loan, schedule(loan)[0]) for loan in all_loans]
	first = pending[0]

	payload = {
		"accounts": accounts,
		"applications": pending,
		"schedule": rows,
		"activity": activity,
		"accounts_note": _("{0} accounts").format(len(accounts)),
		"applications_note": _("{0} in progress").format(len(pending)),
		"schedule_note": one_loan_note(_("Next four instalments"), rows),
		"schedule_url": one_loan_url(rows),
		"activity_note": one_loan_note(_("Last 60 days"), activity),
	}
	payload.update(shell_payload(_("Account overview"), _("View payment details"), all_loans))
	payload.update(labels())
	payload.update(build_summary(all_loans, rows))
	payload["next_flag"] = _("Due in {0} days").format(5)
	payload["tasks"] = [
		{
			"product": first["product"],
			"note": first["note"],
			"stage": first["stage"],
			"stage_tone": first["stage_tone"],
			"url": first["url"],
		}
	]
	payload["tasks_note"] = _("1 thing waiting on you")
	payload.update(
		{
			"application_headline": first["product"],
			"application_stage": first["stage"],
			"application_stage_tone": first["stage_tone"],
			"application_date_label": _("Initiated"),
			"application_date": first["initiated_date"],
			"application_note": first["note"],
			"application_more": "",
			"application_url": first["url"],
		}
	)
	payload.update(next_action(due_soon=True))
	payload["choose_account"] = False

	return as_holder(payload)


def loan_detail(name: str | None) -> dict:
	loan = next((loan for loan in loans() if loan.name == name), loans()[0])
	next_row = schedule(loan)[0]

	payload = shell_payload(loan.loan_product, _("Download statement"), [loan])
	as_holder(payload)
	payload["crumb"] = loan.loan_product
	payload["head_note"] = "{0} · {1}".format(loan.name, STATUS_LABELS[loan.status])

	payload.update(
		{
			"product": loan.loan_product,
			"terms": {
				"sanctioned": money(loan.loan_amount),
				"disbursed": money(loan.disbursed_amount),
				"rate": "{0}%".format(flt(loan.rate_of_interest, 2)),
				"tenure": _("{0} months").format(loan.repayment_periods),
				"instalment": next_row["amount"],
				"frequency": _(loan.repayment_frequency),
				"total": money(loan.total_payment),
				"paid": money(loan.total_amount_paid),
				"next_due": long_date(loan.first_due),
				"written_off": "",
			},
			"summary_note": _("Key information about your loan."),
			"charges": [
				{"label": _("Processing Fee"), "value": money(5900), "detail": _("Deducted from disbursement")},
				{"label": _("Documentation Charges"), "value": money(1180), "detail": _("Collected upfront")},
			],
			# Closed: a request from the preview would reach the server for a loan that does not exist.
			"drawdown": {"loan": loan.name, "open": False, "available": 0, "note": ""},
			"payoff_total": money(round(outstanding_of(loan) * 1.01)),
			"payoff_note": _("As on {0}").format(long_date(nowdate())),
		}
	)

	return payload


def notification_sources() -> tuple[list[dict], list[dict], list[dict]]:
	"""Applications, upcoming instalments and money events, as notifications.current_rows reads them."""
	return applications(), schedule(), decorate_activity(latest(money_events(), 15))
