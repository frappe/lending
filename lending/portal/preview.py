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
	days_until,
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


def refuse_writes():
	"""For an endpoint that sends or saves: in the preview it would act for the editor, or text a stranger."""
	if is_preview():
		frappe.throw(_("This is a preview, so nothing was sent or saved."), frappe.ValidationError)


# Every figure, from the overview to the certificate, comes from one schedule per loan, so they agree.
INSTALMENT_DAYS = 30
DISBURSAL_DAYS = 3


def loans() -> list[frappe._dict]:
	today = getdate(nowdate())
	terms = [
		frappe._dict(
			name=PERSONAL,
			loan_product="Personal Loan",
			status="Active",
			# Started so the next instalment falls five days out.
			posting_date=add_days(today, -265),
			loan_amount=500000,
			disbursed_amount=500000,
			rate_of_interest=11.5,
			repayment_periods=36,
			repayment_frequency="Monthly",
			monthly_repayment_amount=16488,
		),
		frappe._dict(
			name=HOME,
			loan_product="Home Loan",
			status="Partially Disbursed",
			posting_date=add_days(today, -108),
			loan_amount=2500000,
			disbursed_amount=1500000,
			rate_of_interest=8.75,
			repayment_periods=240,
			repayment_frequency="Monthly",
			monthly_repayment_amount=22093,
		),
	]

	for loan in terms:
		rows = instalments(loan)
		paid = [row for row in rows if row.day <= today]
		loan.update(
			total_principal_paid=sum(row.principal for row in paid),
			total_amount_paid=sum(row.total for row in paid),
			total_payment=sum(row.total for row in rows),
			first_due=next(row.day for row in rows if row.day > today),
		)

	return terms


def instalments(loan: dict) -> list[frappe._dict]:
	"""Monthly, interest on the balance; the home loan pays on its drawn share until the rest is out."""
	amount = round(flt(loan.monthly_repayment_amount) * flt(loan.disbursed_amount) / flt(loan.loan_amount))
	balance = flt(loan.disbursed_amount)
	day = getdate(loan.posting_date)
	rows = []

	for _period in range(loan.repayment_periods):
		day = getdate(add_days(day, INSTALMENT_DAYS))
		interest = round(balance * loan.rate_of_interest / 1200)
		principal = min(amount - interest, balance)
		balance -= principal
		rows.append(frappe._dict(day=day, interest=interest, principal=principal, total=interest + principal))

	return rows


def upcoming(loan: dict, count: int = 2) -> list[frappe._dict]:
	return [row for row in instalments(loan) if row.day > getdate(nowdate())][:count]


def repaid(loan: dict, count: int = 2) -> list[frappe._dict]:
	return [row for row in instalments(loan) if row.day <= getdate(nowdate())][-count:]


def schedule(only: dict | None = None) -> list[dict]:
	rows = sorted(
		((row, loan) for loan in ([only] if only else loans()) for row in upcoming(loan)),
		key=lambda pair: pair[0].day,
	)

	return name_once(
		[
			{
				"date": short_date(row.day),
				"day": formatdate(row.day, "dd"),
				"month": formatdate(row.day, "MMM"),
				"year": formatdate(row.day, "yyyy"),
				"product": loan.loan_product,
				"detail": _("Principal {0} · Interest {1}").format(money(row.principal), money(row.interest)),
				"principal": _("Principal {0}").format(money(row.principal)),
				"interest": _("Interest {0}").format(money(row.interest)),
				"amount": money(row.total),
				"url": loan_url(loan.name),
			}
			for row, loan in rows[:4]
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
				add_days(loan.posting_date, DISBURSAL_DAYS),
				_("Loan amount received"),
				disbursed,
				loan.loan_product,
				url,
				amount=disbursed,
			)
		)
		for row in repaid(loan):
			paid = money(row.total)
			events.append(
				event("repaid", row.day, _("Payment made"), paid, loan.loan_product, url, amount=paid)
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
	# build_summary reads the flag from the database, which has none of these loans.
	soonest = min(loan.first_due for loan in all_loans)
	payload["next_flag"] = _("Due in {0} days").format(days_until(soonest)) if days_until(soonest) <= 7 else ""
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


APPLICATION = "APP-PREVIEW-0001"
CUSTOMER = "CUST-PREVIEW-0001"
DOCUMENTS = ("PAN Card", "Salary Slip")


def application_detail() -> dict:
	# Imported here: these modules call into preview.
	from lending.portal.applications import (
		applicant_rows,
		get_application_steps,
		stage_headline,
		stage_label,
		stage_note,
		term_rows,
	)

	application = frappe._dict(
		name=APPLICATION,
		applicant=CUSTOMER,
		applicant_name=HOLDER,
		applicant_type="Customer",
		status="Open",
		docstatus=0,
		posting_date=add_days(nowdate(), -4),
		loan_product="Vehicle Loan",
		loan_amount=850000,
		repayment_method="Repay Over Number of Periods",
		repayment_periods=60,
		rate_of_interest=9.5,
		is_secured_loan=1,
		loan_purpose="A family car",
		**ADDRESS,
	)
	documents = [{"label": _(name), "value": _("Uploaded"), "marker": "✓"} for name in DOCUMENTS]
	headline, headline_note = stage_headline(application, {})

	payload = as_holder(shell_payload(_("Application"), _("Contact us"), loans()))
	payload["head_note"] = "{0} · {1}".format(application.name, stage_label(application))
	payload.update(
		{
			"has_application": True,
			"product": application.loan_product,
			"reference": _("Application {0}").format(application.name),
			"headline": headline,
			"headline_note": headline_note,
			"steps": get_application_steps(application),
			"steps_note": stage_note(application),
			"preview_note": _("As you sent it on {0}").format(long_date(application.posting_date)),
			"terms": term_rows(application),
			"terms_note": _("The loan you asked for"),
			"applicant": applicant_rows(application),
			"applicant_note": _("From your profile"),
			"co_applicants": [],
			"co_applicants_note": _("Just you"),
			"documents": documents,
			"documents_note": _("{0} attached").format(len(documents)),
		}
	)

	return payload


def chosen_loans(name: str | None) -> list[frappe._dict]:
	return [loan for loan in loans() if loan.name == name] or loans()


def statement_entries(loan: dict) -> list[dict]:
	"""The disbursal, then each instalment's interest charged and its payment, with a running balance."""
	disbursed = add_days(loan.posting_date, DISBURSAL_DAYS)
	entries = [{"posting_date": disbursed, "transaction_type": _("Disbursement"), "debit": loan.disbursed_amount}]

	for row in instalments(loan):
		if row.day > getdate(nowdate()):
			break
		entries.append({"posting_date": row.day, "transaction_type": _("Interest"), "debit": row.interest})
		entries.append({"posting_date": row.day, "transaction_type": _("Repayment"), "credit": row.total})

	return entries


def statement_page(loan: str | None, from_date: str, to_date: str) -> dict:
	from lending.portal.statement import statement_body

	chosen = chosen_loans(loan)
	entries = [entry for row in chosen for entry in statement_entries(row)]

	payload = as_holder(shell_payload(_("Statement of account"), "", chosen))
	payload["head_note"] = _("{0} to {1}").format(long_date(from_date), long_date(to_date))
	payload.update(statement_body(entries, from_date, to_date, len(chosen)))
	payload.update(
		{
			"totals_note": _("Across 1 account") if len(chosen) == 1 else _("Across {0} accounts").format(len(chosen)),
			"from_date": from_date,
			"to_date": to_date,
			# No PDF: the download builds it from real loan records.
			"download_url": "",
			"download_label": _("Download PDF"),
		}
	)

	return payload


def certificate_page(year: str | None, loan: str | None) -> dict:
	from lending.portal.statement import (
		PAID_FIELDS,
		account_row,
		certificate_summary,
		requested_year,
		year_options,
	)

	label, start, end = requested_year(year)
	running = getdate(end) > getdate(nowdate())
	chosen = chosen_loans(loan)

	by_loan = {}
	for row in chosen:
		# Paid so far, plus what is still scheduled while the year runs: the real page's provisional rule.
		within = [i for i in instalments(row) if getdate(start) <= i.day <= getdate(end)]
		counted = within if running else [i for i in within if i.day <= getdate(nowdate())]
		amounts = dict.fromkeys((field for field, _title in PAID_FIELDS), 0.0)
		amounts["total_interest_paid"] = sum(i.interest for i in counted)
		amounts["principal_amount_paid"] = sum(i.principal for i in counted)
		by_loan[row.name] = amounts

	totals = {field: sum(amounts[field] for amounts in by_loan.values()) for field, _title in PAID_FIELDS}

	payload = as_holder(shell_payload(_("Interest certificate"), "", chosen))
	payload["head_note"] = _("Financial year {0} · {1}").format(label, _("provisional") if running else _("final"))
	payload.update(
		{
			"rows": [
				{"label": _(title), "value": money(totals[field])} for field, title in PAID_FIELDS if totals[field]
			],
			"rows_note": _("Provisional · paid to date plus instalments due before {0}").format(long_date(end))
			if running
			else _("Final · amounts paid between {0} and {1}").format(long_date(start), long_date(end)),
			"year": label,
			"year_label": _("Financial year {0}").format(label),
			"kind": _("Provisional") if running else _("Final"),
			"kind_theme": "orange" if running else "green",
			"summary": certificate_summary(totals),
			"accounts": [account_row(row, by_loan[row.name]) for row in chosen],
			"accounts_note": _("1 account covered")
			if len(chosen) == 1
			else _("{0} accounts covered").format(len(chosen)),
			"years": year_options(),
			"disclaimer": _(
				"This certificate reports amounts paid. It states no tax relief; please consult your tax adviser."
			),
			"download_url": "",
			"download_label": _("Download {0} certificate").format(label),
		}
	)

	return payload


ADDRESS = {
	"address_line_1": "14, Lakeview Apartments",
	"address_line_2": "MG Road",
	"city": "Bengaluru",
	"state": "Karnataka",
	"zip_code": "560001",
	"country": "India",
}

CONTACT = {"email": "priya.sharma@example.com", "mobile": "+91 98450 12345", "phone": ""}


def profile_page() -> dict:
	from lending.portal.profile import row

	address = ", ".join(value for value in ADDRESS.values() if value)
	values = {
		"customer_name": HOLDER,
		"customer_type": "Individual",
		"tax_id": "ABCPS1234K",
		**CONTACT,
		"address_line1": ADDRESS["address_line_1"],
		"address_line2": ADDRESS["address_line_2"],
		"city": ADDRESS["city"],
		"state": ADDRESS["state"],
		"pincode": ADDRESS["zip_code"],
		"country": ADDRESS["country"],
	}

	payload = as_holder(shell_payload(_("Personal details"), _("Contact us"), loans()))
	payload.update(
		{
			"records": [
				row(_("Name"), HOLDER, CUSTOMER),
				row(_("Registered as"), values["customer_type"]),
				row(_("Tax id"), values["tax_id"]),
				row(_("Email"), CONTACT["email"]),
				row(_("Mobile"), CONTACT["mobile"]),
				row(_("Phone"), CONTACT["phone"]),
				row(_("Address"), address),
			],
			"records_note": _("Your profile"),
			"edit_note": _(
				"Contact details and address can be corrected. Name and tax id come from your verified records — write to us to change those."
			),
			"form_customer": CUSTOMER,
			"forms": {CUSTOMER: values},
			"customer_options": [{"label": HOLDER, "value": CUSTOMER}],
			"form_note": _("Editing {0}").format(HOLDER),
			"save_label": _("Save my details"),
			**{f"form_{field}": value for field, value in values.items() if field not in ("customer_name", "customer_type", "tax_id")},
		}
	)

	return payload


def notification_sources() -> tuple[list[dict], list[dict], list[dict]]:
	"""Applications, upcoming instalments and money events, as notifications.current_rows reads them."""
	return applications(), schedule(), decorate_activity(latest(money_events(), 15))
