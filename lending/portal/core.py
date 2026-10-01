# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, formatdate, getdate, nowdate
from frappe.website.utils import get_portal_sidebar_items

from lending.portal.brand import brand_style

# Never shown to borrowers: exposing delinquency labels invites disputes.
WITHHELD_FROM_BORROWER = (
	"is_npa",
	"manual_npa",
	"days_past_due",
	"classification_code",
	"classification_name",
	"watch_period_end_date",
	"freeze_account",
	"loan_partner",
	"fldg_triggered",
)

LIVE_STATUSES = ("Sanctioned", "Partially Disbursed", "Disbursed", "Active", "Loan Closure Requested")
SETTLED_STATUSES = ("Closed", "Written Off", "Settled")

STATUS_LABELS = {
	"Draft": "Not yet active",
	"Sanctioned": "Sanctioned, awaiting disbursement",
	"Partially Disbursed": "Partly disbursed",
	"Disbursed": "Regular",
	"Active": "Regular",
	"Loan Closure Requested": "Closure requested",
	"Closed": "Closed",
	"Written Off": "Written off",
	"Settled": "Settled",
}

# No red: the portal palette has no danger pair, so "warn" stands in for it.
STATUS_TONES = {
	"Disbursed": "ok",
	"Active": "ok",
	"Written Off": "warn",
}

DEFAULT_BRAND_NAME = "Frappe Lending"

PORTAL_ROUTE_PREFIX = "/borrower-portal/"

APPLICATION_STAGES = {
	"Open": "Under review",
	"Approved": "Approved",
	"Rejected": "Not approved",
}

STAGE_TONES = {
	"Approved": "ok",
	"Rejected": "warn",
}

CHOSEN_LOAN_KEY = "lending_portal_chosen_loan"


def assert_portal_enabled():
	if not frappe.db.get_single_value("Lending Settings", "enable_borrower_portal"):
		raise frappe.PageDoesNotExistError


def assert_public_apply_enabled():
	assert_portal_enabled()

	if not frappe.db.get_single_value("Lending Settings", "enable_public_apply"):
		raise frappe.PageDoesNotExistError


def get_portal_customers() -> list[str]:
	assert_portal_enabled()

	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in to view your account."), frappe.PermissionError)

	return frappe.get_all(
		"Customer",
		filters=[["Portal User", "user", "=", user]],
		pluck="name",
	)


@contextmanager
def as_administrator():
	# set_user wipes the session and form_dict; restore both (session in place) or the borrower is logged out.
	caller = frappe.session.user
	session, form_dict = frappe.local.session.copy(), frappe.local.form_dict
	frappe.set_user("Administrator")  # nosemgrep
	try:
		yield
	finally:
		frappe.set_user(caller)  # nosemgrep
		frappe.local.session.update(session)
		frappe.local.form_dict = form_dict


def assert_owns(doctype: str, name: str) -> str:
	# applicant is a Dynamic Link: an Employee ID can equal a Customer name the borrower chose.
	record = frappe.db.get_value(doctype, name, ["applicant_type", "applicant"], as_dict=True)
	if (
		not record
		or record.applicant_type != "Customer"
		or record.applicant not in get_portal_customers()
	):
		raise frappe.PermissionError(_("Not permitted"))

	return record.applicant


def clean(value) -> str:
	return frappe.utils.strip_html(str(value or "")).strip()


def money(amount) -> str:
	return fmt_money(flt(amount), currency=frappe.defaults.get_global_default("currency") or "INR")


def long_date(value) -> str:
	return formatdate(value, "d MMMM yyyy") if value else ""


def short_date(value) -> str:
	return formatdate(value, "dd MMM yyyy") if value else ""


def days_until(value) -> int:
	return (getdate(value) - getdate(nowdate())).days


def days_ago(value) -> str:
	"""Not pretty_date: it reads a bare date as midnight. Full phrases so translators can pluralise."""
	days = -days_until(value)

	if days <= 0:
		return _("Today")
	if days == 1:
		return _("Yesterday")
	if days < 7:
		return _("{0} days ago").format(days)

	if days < 30:
		weeks = days // 7
		return _("1 week ago") if weeks == 1 else _("{0} weeks ago").format(weeks)

	if days < 365:
		months = days // 30
		return _("1 month ago") if months == 1 else _("{0} months ago").format(months)

	years = days // 365

	return _("1 year ago") if years == 1 else _("{0} years ago").format(years)


def loan_url(name: str) -> str:
	return f"/borrower-portal/loan/{name}" if name else ""


def application_url(name: str) -> str:
	return f"/borrower-portal/application/{name}" if name else ""


def current_route() -> str:
	# Not frappe.request: off a request that proxy raises instead of returning None.
	request = getattr(frappe.local, "request", None)

	return "/" + (getattr(request, "path", "") or "").strip("/")


def is_current(item: dict, route: str) -> bool:
	if route == item.get("route"):
		return True

	covers = item.get("covers")

	# The trailing slash keeps /applications from matching covers=/application.
	return bool(covers) and route.startswith(covers + "/")


def nav_items() -> list[dict]:
	# get_portal_sidebar_items also returns other apps' rows (ERPNext Orders, Invoices).
	route = current_route()

	return [
		{
			"nav_title": _(item.get("title") or item.get("label") or ""),
			"nav_route": item.get("route"),
			# Bound to aria-current, hence "page"/"false" rather than a bool.
			"nav_current": "page" if is_current(item, route) else "false",
		}
		for item in get_portal_sidebar_items()
		if (item.get("route") or "").startswith(PORTAL_ROUTE_PREFIX)
	]


def shell_payload(crumb: str, action_label: str, loans: list[dict]) -> dict:
	return {
		"as_on": long_date(nowdate()),
		"nav_items": nav_items(),
		**brand_payload(),
		**footer_payload(),
		"initials": initials(),
		"holder_name": holder_name(),
		"head_note": head_note(),
		**account_status(loans),
		**account_switch(),
		"crumb": crumb,
		"action_label": action_label,
	}


def chosen_loan(loans: list[dict]) -> dict | None:
	if len(loans) == 1:
		return loans[0]

	chosen = frappe.defaults.get_user_default(CHOSEN_LOAN_KEY)

	# Matching against `loans` is the ownership check on the stored choice.
	return next((loan for loan in loans if loan.name == chosen), None)


def account_switch() -> dict:
	customers = get_portal_customers()

	return {"can_switch": len(get_loans(customers)) > 1 if customers else False}


@frappe.whitelist()
def get_dashboard() -> dict:
	"""Overview page payload, pre-formatted since blocks bind values straight into props."""
	customers = get_portal_customers()
	if not customers:
		return empty_dashboard()

	all_loans = get_loans(customers)
	chosen = chosen_loan(all_loans)
	loans = [chosen] if chosen else all_loans
	schedule = get_upcoming_repayments(loans)
	applications = get_applications(customers)
	activity = get_timeline(customers, loans)
	accounts = [present_loan(loan, len(customers) > 1) for loan in loans]

	payload = {
		"accounts": accounts,
		"applications": applications,
		"schedule": schedule,
		"activity": activity,
		"accounts_note": (
			_("1 account") if len(accounts) == 1 else _("{0} accounts").format(len(accounts))
		),
		"applications_note": _("{0} in progress").format(len(applications)),
		"schedule_note": one_loan_note(_("Next four instalments"), schedule),
		"schedule_url": one_loan_url(schedule),
		"activity_note": one_loan_note(_("Last 60 days"), activity),
	}
	payload.update(shell_payload(_("Account overview"), _("View payment details"), loans))
	payload.update(labels())
	payload.update(build_summary(loans, schedule))
	payload["tasks"] = waiting_on_borrower(applications)
	payload["tasks_note"] = tasks_note(payload["tasks"])
	payload.update(application_lead(applications) if applications else enquiry_lead(open_lead()))
	# Must follow build_summary, which sets next_flag.
	payload.update(next_action(bool(payload["next_flag"])))
	payload["choose_account"] = chosen is None and len(all_loans) > 1

	return payload


def empty_dashboard() -> dict:
	payload = {
		"accounts": [],
		"applications": [],
		"schedule": [],
		"activity": [],
		"accounts_note": _("Nothing to show"),
		"applications_note": _("Nothing to show"),
		"schedule_note": _("Nothing due"),
		"activity_note": _("No activity"),
		"next_amount": "",
		"next_note": _("Nothing due"),
		"next_flag": "",
		"outstanding": money(0),
		"outstanding_note": _("No live accounts"),
		"sanctioned": money(0),
		"sanctioned_note": "",
		"sanctioned_line": "",
		"tasks": [],
		"tasks_note": "",
	}
	# A new borrower has no Customer yet but may already have a Loan Lead.
	payload.update(enquiry_lead(open_lead()))
	payload.update(shell_payload(_("Account overview"), _("View payment details"), []))
	payload.update(labels())
	payload.update(next_action(due_soon=False))

	return payload


REPAYMENTS_ROUTE = "/borrower-portal/repayments"


def waiting_on_borrower(applications: list[dict]) -> list[dict]:
	"""Unsent applications only; due instalments are already covered by the payment button."""
	return [
		{
			"product": row["product"],
			"note": row["note"] or row["reference"],
			"stage": row["stage"],
			"stage_tone": row["stage_tone"],
			"url": row["url"],
		}
		for row in applications
		if row["needs_borrower"]
	]


def tasks_note(tasks: list[dict]) -> str:
	if not tasks:
		return ""

	return _("1 thing waiting on you") if len(tasks) == 1 else _("{0} things waiting on you").format(len(tasks))


def application_lead(applications: list[dict]) -> dict:
	if not applications:
		return {
			"application_headline": "",
			"application_stage": "",
			"application_stage_tone": "",
			"application_date_label": "",
			"application_date": "",
			"application_note": _("Nothing in progress"),
			"application_more": "",
			"application_url": "",
		}

	# get_applications orders by posting_date desc, so the first row is the newest.
	first = applications[0]

	return {
		"application_headline": first["product"],
		"application_stage": first["stage"],
		"application_stage_tone": first["stage_tone"],
		"application_date_label": _("Initiated"),
		"application_date": first["initiated_date"],
		"application_note": first["note"],
		"application_more": (
			_("{0} in progress").format(len(applications)) if len(applications) > 1 else ""
		),
		"application_url": first["loan_url"] or first["url"],
	}


def enquiry_lead(lead: dict | None) -> dict:
	if not lead:
		return application_lead([])

	declined = lead.prequalification_status == "Not Pre-Qualified"
	with_us = lead.prequalification_status not in ("Pre-Qualified", "Not Pre-Qualified")

	return {
		"application_headline": lead.loan_product,
		"application_stage": tracker_stage(lead),
		"application_stage_tone": "warn" if declined else "info" if with_us else "ok",
		"application_date_label": _("Started"),
		"application_date": short_date(lead.creation),
		"application_note": "" if declined else _("Your loan application process has started"),
		"application_more": "",
		# With no application named, that page shows the open enquiry.
		"application_url": "/borrower-portal/applications",
	}


def next_action(due_soon: bool) -> dict:
	return {
		"action_label": _("View payment details"),
		"action_href": REPAYMENTS_ROUTE,
		# A data attribute styled by ACTION_TONE_CSS; one block cannot carry two style sets.
		"action_urgent": "1" if due_soon else "0",
	}


def labels() -> dict:
	"""Translated here since page scripts lack _(); a function so _() runs per request."""
	return {
		"label_application": _("Loan application"),
		"label_next": _("Next repayment"),
		"label_outstanding": _("Total outstanding"),
		"label_sanctioned": _("Total sanctioned"),
	}


def holder_name() -> str:
	return frappe.db.get_value("User", frappe.session.user, "full_name") or ""


def head_note() -> str:
	return _("{0} · figures as on {1}").format(holder_name(), long_date(nowdate()))


def initials() -> str:
	words = (holder_name() or frappe.session.user).split()
	letters = [word[0] for word in words[:2] if word]

	return "".join(letters).upper() or "?"


def portal_settings(*fieldnames) -> frappe._dict:
	return frappe._dict(
		{name: frappe.db.get_single_value("Lending Settings", name) for name in fieldnames}
	)


def brand_name() -> str:
	return portal_settings("portal_brand_name").portal_brand_name or DEFAULT_BRAND_NAME


def brand_payload() -> dict:
	settings = portal_settings(
		"portal_brand_name",
		"portal_logo",
		"portal_support_email",
		"portal_primary_color",
		"portal_secondary_color",
	)
	logo = (settings.portal_logo or "").strip()
	support = (settings.portal_support_email or "").strip()

	return {
		"brand_name": settings.portal_brand_name or DEFAULT_BRAND_NAME,
		"brand_logo": logo,
		"show_wordmark": 0 if logo else 1,
		"support_email": support,
		"support_href": f"mailto:{support}" if support else "#",
		"brand_style": brand_style(settings.portal_primary_color, settings.portal_secondary_color),
	}


def copyright_note() -> str:
	settings = portal_settings("portal_copyright", "portal_brand_name")
	brand = settings.portal_brand_name or DEFAULT_BRAND_NAME
	year = str(getdate(nowdate()).year)

	written = clean(settings.portal_copyright)
	if written:
		# replace, not format: a stray brace in the setting must not raise.
		return written.replace("{year}", year)

	# rstrip so "Pvt. Ltd." does not end in two stops.
	return _("Copyright © {0} {1}. All rights reserved.").format(year, brand.rstrip("."))


def footer_links() -> list[dict]:
	rows = frappe.get_all(
		"Top Bar Item",
		filters={"parent": "Lending Settings", "parentfield": "portal_footer_links"},
		fields=["label", "url"],
		order_by="idx asc",
	)

	links = [
		{"footer_label": clean(row.label), "footer_href": clean(row.url)}
		for row in rows
		if clean(row.label) and clean(row.url)
	]

	# Lenders must publish a grievance address, so the app adds it rather than trusting a row.
	support = (portal_settings("portal_support_email").portal_support_email or "").strip()
	if support:
		links.append({"footer_label": _("Contact us"), "footer_href": f"mailto:{support}"})

	return links


def footer_payload() -> dict:
	return {"copyright_note": copyright_note(), "footer_links": footer_links()}


def get_loans(customers: list[str]) -> list[dict]:
	"""Never select WITHHELD_FROM_BORROWER fields here."""
	return frappe.get_all(
		"Loan",
		filters={"applicant_type": "Customer", "applicant": ["in", customers], "docstatus": 1},
		fields=[
			"name",
			"applicant",
			"loan_product",
			"status",
			"posting_date",
			"loan_amount",
			"rate_of_interest",
			"repayment_periods",
			"repayment_frequency",
			"monthly_repayment_amount",
			"disbursed_amount",
			"total_principal_paid",
			"closure_date",
		],
		order_by="status asc, posting_date desc",
	)


def outstanding_of(loan: dict) -> float:
	# total_principal_paid is not always written back on migrated data, so trust the status.
	if loan.status in SETTLED_STATUSES:
		return 0

	return max(flt(loan.disbursed_amount) - flt(loan.total_principal_paid), 0)


def undrawn_of(loan: dict) -> float:
	return max(flt(loan.loan_amount) - flt(loan.disbursed_amount), 0)


def is_live(loan: dict) -> bool:
	return loan.status in LIVE_STATUSES


def status_label(loan: dict) -> str:
	return STATUS_LABELS.get(loan.status, loan.status)


def present_loan(loan: dict, show_customer: bool) -> dict:
	label = status_label(loan)
	undrawn = undrawn_of(loan)
	next_row = next_repayment_for(loan.name)

	return {
		"name": loan.name,
		"url": loan_url(loan.name),
		"product": loan.loan_product,
		"terms": "{0} · {1}% p.a. · {2} {3}".format(
			loan.name,
			flt(loan.rate_of_interest, 2),
			loan.repayment_periods,
			(loan.repayment_frequency or "Monthly").lower(),
		),
		"status_label": label,
		"tone": STATUS_TONES.get(loan.status, ""),
		"customer": loan.applicant if show_customer else "",
		"next_date": short_date(next_row.get("payment_date")) if next_row else "—",
		"next_amount": money(next_row.get("total_payment")) if next_row else "",
		"outstanding": money(outstanding_of(loan)),
		"against": (
			_("{0} undrawn").format(money(undrawn)) if undrawn else _("of {0}").format(money(loan.loan_amount))
		),
		"closed_note": closed_note(loan),
	}


def closed_note(loan: dict) -> str:
	if loan.status not in SETTLED_STATUSES:
		return ""

	if loan.closure_date:
		return f"{STATUS_LABELS.get(loan.status, loan.status)} {short_date(loan.closure_date)}"

	return STATUS_LABELS.get(loan.status, loan.status)


def active_schedule_names(loan_names: list[str]) -> list[str]:
	if not loan_names:
		return []

	return frappe.get_all(
		"Loan Repayment Schedule",
		filters={"loan": ["in", loan_names], "docstatus": 1, "status": "Active"},
		pluck="name",
	)


def next_repayment_for(loan_name: str) -> dict:
	rows = upcoming_rows(active_schedule_names([loan_name]), limit=1)
	return rows[0] if rows else {}


def upcoming_rows(schedule_names: list[str], limit: int = 4) -> list[dict]:
	"""Skips permissions; callers must pass only schedules of the borrower's own loans."""
	if not schedule_names:
		return []

	return frappe.get_all(
		"Repayment Schedule",
		filters={
			"parent": ["in", schedule_names],
			"parenttype": "Loan Repayment Schedule",
			"payment_date": [">=", nowdate()],
		},
		fields=["parent", "payment_date", "total_payment", "principal_amount", "interest_amount"],
		order_by="payment_date asc",
		limit=limit,
		ignore_permissions=True,
	)


def get_upcoming_repayments(loans: list[dict], limit: int = 4) -> list[dict]:
	live = [loan.name for loan in loans if is_live(loan)]
	product_of = {loan.name: loan.loan_product for loan in loans}
	schedule_to_loan = {
		row.name: row.loan
		for row in frappe.get_all(
			"Loan Repayment Schedule",
			filters={"loan": ["in", live], "docstatus": 1, "status": "Active"},
			fields=["name", "loan"],
		)
	} if live else {}

	rows = upcoming_rows(list(schedule_to_loan), limit=limit)
	presented = []
	for row in rows:
		loan_name = schedule_to_loan.get(row.parent)
		presented.append(
			{
				"date": short_date(row.payment_date),
				"day": formatdate(row.payment_date, "dd"),
				"month": formatdate(row.payment_date, "MMM"),
				"year": formatdate(row.payment_date, "yyyy"),
				"product": product_of.get(loan_name, ""),
				"detail": _("Principal {0} · Interest {1}").format(
					money(row.principal_amount), money(row.interest_amount)
				),
				"principal": _("Principal {0}").format(money(row.principal_amount)),
				"interest": _("Interest {0}").format(money(row.interest_amount)),
				"amount": money(row.total_payment),
				"url": loan_url(loan_name),
			}
		)

	return name_once(presented)


def one_loan_note(base: str, rows: list[dict]) -> str:
	products = {row["product"] for row in rows}

	return _("{0} · {1}").format(base, products.pop()) if len(products) == 1 else base


def one_loan_url(rows: list[dict]) -> str:
	urls = {row["url"] for row in rows}

	return urls.pop() if len(urls) == 1 else ""


def name_once(rows: list[dict]) -> list[dict]:
	"""Drops the loan name from rows when all share it; keeps product/detail for notifications."""
	one_loan = len({row["product"] for row in rows}) == 1

	for row in rows:
		row["title"] = row["detail"] if one_loan else row["product"]
		row["sub"] = "" if one_loan else row["detail"]

	return rows


def build_summary(loans: list[dict], schedule: list[dict]) -> dict:
	live = [loan for loan in loans if is_live(loan)]
	outstanding = sum(outstanding_of(loan) for loan in live)
	sanctioned = sum(flt(loan.loan_amount) for loan in loans)
	undrawn = sum(undrawn_of(loan) for loan in live)
	drawn = sum(flt(loan.disbursed_amount) for loan in live)
	repaid = sum(flt(loan.total_principal_paid) for loan in live)
	first = schedule[0] if schedule else {}
	sanctioned_amount = money(sanctioned)
	sanctioned_note = _("{0} undrawn").format(money(undrawn)) if undrawn else _("Fully drawn")

	return {
		"next_amount": first.get("amount", ""),
		"next_note": (_("Due {0}").format(first.get("date")) if first else _("Nothing due")),
		"next_flag": next_flag(loans),
		"outstanding": money(outstanding),
		"outstanding_note": (
			_("Across 1 live account")
			if len(live) == 1
			else _("Across {0} live accounts").format(len(live))
		),
		"sanctioned": sanctioned_amount,
		"sanctioned_note": sanctioned_note,
		"sanctioned_line": standing_line(sanctioned, undrawn, drawn, repaid),
	}


def standing_line(sanctioned: float, undrawn: float, drawn: float, repaid: float) -> str:
	if not sanctioned:
		return ""

	if undrawn:
		return _("Total sanctioned {0} · {1} undrawn").format(money(sanctioned), money(undrawn))

	if drawn:
		return _("{0} of {1} principal repaid").format(money(repaid), money(drawn))

	return _("Total sanctioned {0} · {1}").format(money(sanctioned), _("Fully drawn"))


def next_flag(loans: list[dict]) -> str:
	rows = upcoming_rows(active_schedule_names([loan.name for loan in loans if is_live(loan)]), limit=1)
	if not rows:
		return ""

	days = days_until(rows[0].payment_date)
	if days <= 0:
		return _("Due today")

	return _("Due in {0} days").format(days) if days <= 7 else ""


def account_status(loans: list[dict]) -> dict:
	live = [loan for loan in loans if is_live(loan)]
	if not live:
		return {"account_status": _("No live accounts"), "account_tone": ""}

	overdue = frappe.db.count(
		"Loan Demand",
		{
			"loan": ["in", [loan.name for loan in live]],
			"docstatus": 1,
			"demand_date": ["<", nowdate()],
			"outstanding_amount": [">", 0],
		},
	)

	if overdue:
		return {"account_status": _("Payment overdue"), "account_tone": "warn"}

	# One live account already shows its standing in its own row.
	if len(live) == 1:
		return {"account_status": "", "account_tone": "ok"}

	return {"account_status": _("All accounts regular"), "account_tone": "ok"}


def loans_by_application(applications: list[str]) -> dict:
	"""Needed because Loan Application.status stays Open after create_loan books the loan."""
	if not applications:
		return {}

	rows = frappe.get_all(
		"Loan",
		filters={"loan_application": ["in", applications], "docstatus": 1},
		fields=["name", "status", "loan_application"],
	)

	return {row.loan_application: row for row in rows}


def application_stage(application: dict, needs_borrower: bool, loan: dict | None) -> tuple[str, str]:
	if needs_borrower:
		return _("Action required"), "warn"

	if loan:
		return _("Loan sanctioned"), "ok"

	return APPLICATION_STAGES.get(application.status, application.status), STAGE_TONES.get(
		application.status, ""
	)


def leads_for_login() -> list[dict]:
	"""Joined on the session email, never a request value: a Loan Lead has no Customer yet."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in to view your account."), frappe.PermissionError)

	return frappe.get_all(
		"Loan Lead",
		filters={"email": user, "docstatus": ["<", 2]},
		fields=[
			"name",
			"applicant_name",
			"loan_product",
			"loan_amount",
			"status",
			"prequalification_status",
			"creation",
		],
		order_by="creation desc",
	)


def open_lead() -> dict | None:
	"""The newest Loan Lead not yet converted to a Loan Application."""
	leads = leads_for_login()
	converted = set(
		frappe.get_all(
			"Loan Application",
			filters={"loan_lead": ["in", [lead.name for lead in leads]]},
			pluck="loan_lead",
			ignore_permissions=True,
		)
		if leads
		else []
	)

	return next((lead for lead in leads if lead.name not in converted), None)


def tracker_stage(lead: dict) -> str:
	if lead.prequalification_status == "Not Pre-Qualified":
		return _("Not taken forward")

	if lead.prequalification_status == "Pre-Qualified":
		return _("Pre-qualified, awaiting your application")

	return _("With our team")


def get_applications(customers: list[str]) -> list[dict]:
	rows = frappe.get_all(
		"Loan Application",
		filters={
			"applicant_type": "Customer",
			"applicant": ["in", customers],
			"status": "Open",
			"docstatus": ["<", 2],
		},
		fields=["name", "loan_product", "loan_amount", "status", "posting_date", "docstatus"],
		order_by="posting_date desc",
	)

	booked = loans_by_application([row.name for row in rows])

	presented = []
	for row in rows:
		needs_borrower = row.docstatus == 0
		loan = booked.get(row.name)
		stage, stage_tone = application_stage(row, needs_borrower, loan)
		presented.append(
			{
				"name": row.name,
				"url": application_url(row.name),
				"loan_url": loan_url(loan.name) if loan else "",
				"product": row.loan_product,
				"reference": "{0} · initiated {1}".format(row.name, long_date(row.posting_date)),
				"initiated": _("Initiated on {0}").format(long_date(row.posting_date)),
				"initiated_date": short_date(row.posting_date),
				"stage": stage,
				"stage_tone": stage_tone,
				"needs_borrower": needs_borrower,
				"amount": money(row.loan_amount),
				"note": draft_note(row.name) if needs_borrower else "",
			}
		)

	return presented


def draft_note(application: str) -> str:
	# No missing-documents checklist: Loan Product defines no expected document types.
	uploaded = frappe.db.count(
		"Loan Application Document", {"parent": application, "parenttype": "Loan Application"}
	)

	return (
		_("Submit to start the review · {0} documents attached").format(uploaded)
		if uploaded
		else _("Submit to start the review")
	)


# Tie-break for same-day events.
EVENT_ORDER = {"created": 0, "submitted": 1, "sanctioned": 2, "disbursed": 3, "repaid": 4}


def event(kind, day, title, line, product, url, tone="ok", amount=""):
	return {
		"date": short_date(day),
		"when": days_ago(day),
		"sort": (str(getdate(day)), EVENT_ORDER[kind]),
		"title": title,
		"line": line,
		"product": product,
		"amount": amount,
		"url": url,
		"tone": tone,
	}


def latest(events: list[dict], limit: int) -> list[dict]:
	events.sort(key=lambda event: event["sort"], reverse=True)
	for event in events:
		event.pop("sort", None)

	return events[:limit]


def money_events(loans: list[dict], limit: int) -> list[dict]:
	loan_names = [loan.name for loan in loans]
	if not loan_names:
		return []

	product_of = {loan.name: loan.loan_product for loan in loans}
	events = []

	for row in frappe.get_all(
		"Loan Repayment",
		filters={"against_loan": ["in", loan_names], "docstatus": 1},
		fields=["against_loan", "posting_date", "amount_paid"],
		order_by="posting_date desc",
		limit=limit,
	):
		amount = money(row.amount_paid)
		events.append(
			event(
				"repaid",
				row.posting_date,
				_("Payment made"),
				amount,
				product_of.get(row.against_loan, ""),
				loan_url(row.against_loan),
				amount=amount,
			)
		)

	for row in frappe.get_all(
		"Loan Disbursement",
		filters={"against_loan": ["in", loan_names], "docstatus": 1},
		fields=["against_loan", "disbursement_date", "disbursed_amount"],
		order_by="disbursement_date desc",
		limit=limit,
	):
		amount = money(row.disbursed_amount)
		events.append(
			event(
				"disbursed",
				row.disbursement_date,
				_("Loan amount received"),
				amount,
				product_of.get(row.against_loan, ""),
				loan_url(row.against_loan),
				amount=amount,
			)
		)

	return events


def get_activity(loans: list[dict], limit: int = 5) -> list[dict]:
	events = latest(money_events(loans, limit), limit)

	one_loan = len({event["product"] for event in events}) == 1
	for event in events:
		event["sub"] = "" if one_loan else event["product"]
		event["note"] = " · ".join(
			part for part in (event["amount"], event["sub"], event["when"]) if part
		)

	return events


def submission_times(applications: list[str]) -> dict:
	"""Read from Version rows, since Loan Application stores no submission timestamp."""
	if not applications:
		return {}

	submitted = {}
	for version in frappe.get_all(
		"Version",
		filters={
			"ref_doctype": "Loan Application",
			"docname": ["in", applications],
			"data": ["like", '%"docstatus"%'],
		},
		fields=["docname", "creation", "data"],
		order_by="creation asc",
	):
		changed = frappe.parse_json(version.data or "{}").get("changed") or []
		if ["docstatus", 0, 1] in changed:
			submitted.setdefault(version.docname, version.creation)

	return submitted


def milestone_events(customers: list[str], loans: list[dict], limit: int) -> list[dict]:
	applications = frappe.get_all(
		"Loan Application",
		filters={"applicant_type": "Customer", "applicant": ["in", customers], "docstatus": ["<", 2]},
		fields=["name", "loan_product", "creation", "posting_date", "docstatus"],
		order_by="creation desc",
		limit=limit,
	)
	submitted = submission_times([row.name for row in applications if row.docstatus == 1])
	events = []

	for row in applications:
		url = application_url(row.name)
		events.append(
			event(
				"created",
				row.creation,
				_("Application started"),
				_("You started a new loan application."),
				row.loan_product,
				url,
				tone="",
			)
		)
		if row.docstatus == 1:
			events.append(
				event(
					"submitted",
					submitted.get(row.name) or row.posting_date,
					_("Application submitted"),
					_("Your application has been submitted."),
					row.loan_product,
					url,
					tone="",
				)
			)

	for loan in loans:
		events.append(
			event(
				"sanctioned",
				loan.posting_date,
				_("Loan sanctioned"),
				_("Your loan has been sanctioned."),
				loan.loan_product,
				loan_url(loan.name),
			)
		)

	return events


def get_timeline(customers: list[str], loans: list[dict], limit: int = 5) -> list[dict]:
	"""Money plus milestones; the bell uses get_activity since its read state hashes row text."""
	events = latest(money_events(loans, limit) + milestone_events(customers, loans, limit), limit)

	one_loan = len({event["product"] for event in events}) == 1
	for index, event in enumerate(events):
		event["sub"] = "" if one_loan else event["product"]
		event["note"] = " · ".join(part for part in (event.pop("line"), event["sub"]) if part)

		following = events[index + 1] if index + 1 < len(events) else None
		if not following:
			event["stem"] = ""
		elif event["tone"] == following["tone"] == "ok":
			event["stem"] = "ok"
		else:
			event["stem"] = "plain"

	return events
