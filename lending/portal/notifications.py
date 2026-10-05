# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import hashlib
import json

import frappe
from frappe import _

from lending.portal import preview
from lending.portal.core import (
	get_activity,
	get_applications,
	get_loans,
	get_portal_customers,
	get_upcoming_repayments,
)

ATTENTION_LIMIT = 12
SCHEDULE_LIMIT = 4
ACTIVITY_LIMIT = 15

# Per-user DefaultValue holding seen row keys; capped by the limits above, so no DocType.
READ_KEY = "lending_portal_alerts_read"


def row_key(row: dict) -> str:
	# Rows are derived, not stored, so identity is a digest of the translated text.
	said = "|".join((row["title"], row["note"], row["when"], row["url"]))

	return hashlib.sha256(said.encode()).hexdigest()[:16]


def read_keys() -> set[str]:
	try:
		return set(json.loads(frappe.defaults.get_user_default(READ_KEY) or "[]"))
	except ValueError:
		return set()


def current_rows() -> tuple[list[dict], list[dict]]:
	if preview.is_preview():
		applications, schedule, events = preview.notification_sources()
	else:
		customers = get_portal_customers()
		loans = get_loans(customers) if customers else []
		applications = get_applications(customers) if customers else []
		schedule = get_upcoming_repayments(loans, limit=SCHEDULE_LIMIT)
		events = get_activity(loans, limit=ACTIVITY_LIMIT)

	return attention_rows(applications, schedule), activity_rows(events)


@frappe.whitelist()
def get_notifications() -> dict:
	waiting, activity = current_rows()
	shown = waiting[:ATTENTION_LIMIT]
	seen = read_keys()

	for row in shown + activity:
		row["read"] = row_key(row) in seen

	return {
		"attention": shown,
		"attention_note": attention_note(len(waiting)),
		"activity": activity,
		"activity_note": (
			_("The last {0} events on your accounts").format(len(activity))
			if activity
			else _("Nothing has happened yet")
		),
	}


@frappe.whitelist(methods=["POST"])
def mark_all_as_read() -> dict:
	"""Mark the server's current rows read; nothing comes from the browser, which also prunes stale keys."""
	waiting, activity = current_rows()
	keys = sorted({row_key(row) for row in waiting[:ATTENTION_LIMIT] + activity})
	frappe.defaults.set_user_default(READ_KEY, json.dumps(keys))

	return {"read": len(keys)}


def attention_note(total: int) -> str:
	if not total:
		return _("Nothing to do")

	if total > ATTENTION_LIMIT:
		return _("{0} of {1} waiting on you").format(ATTENTION_LIMIT, total)

	return _("{0} waiting on you").format(total)


def attention_rows(applications: list[dict], schedule: list[dict]) -> list[dict]:
	rows = [
		{
			"title": application["product"],
			"note": application["note"],
			"when": application["stage"],
			"url": application["url"],
		}
		for application in applications
		if application["needs_borrower"]
	]

	rows.extend(
		{
			"title": instalment["product"],
			"note": instalment["detail"],
			"when": _("Due {0} · {1}").format(instalment["date"], instalment["amount"]),
			# Never empty: a blank href renders as a dead link.
			"url": instalment.get("url") or "/borrower-portal/loans",
		}
		for instalment in schedule
	)

	return rows


def activity_rows(events: list[dict]) -> list[dict]:
	return [
		{
			"title": event["title"],
			"note": event["sub"],
			"when": _("{0} · {1}").format(event["amount"], event["date"]),
			"url": "/borrower-portal/statement",
		}
		for event in events
	]
