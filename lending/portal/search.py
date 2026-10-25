# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# Filters the already-scoped get_loans/get_applications output rather than querying with LIKE.

import frappe
from frappe import _

from lending.portal.core import (
	application_url,
	clean,
	get_applications,
	get_loans,
	get_portal_customers,
	loan_url,
	money,
	nav_items,
	outstanding_of,
	status_label,
)

RESULT_LIMIT = 5


def results_for(query: str, customers: list[str], limit: int = RESULT_LIMIT) -> tuple[list[dict], str]:
	if not query:
		return page_rows()[:limit], results_note(query, 0, limit)

	found = matches(query, searchable(customers))

	return found[:limit], results_note(query, len(found), limit)


def page_rows() -> list[dict]:
	return [
		{"title": item["nav_title"], "note": "", "kind": _("Page"), "url": item["nav_route"]}
		for item in nav_items()
	]


@frappe.whitelist(methods=["GET"])
def find() -> dict:
	"""Ctrl+K palette results; no shell payload since it is called on every keystroke pause."""
	results, note = results_for(clean(frappe.form_dict.get("q")), get_portal_customers())

	return {"results": results, "note": note}


def searchable(customers: list[str]) -> list[dict]:
	rows = page_rows()
	if not customers:
		return rows

	applications = get_applications(customers)
	rows.extend(loan_row(loan) for loan in get_loans(customers))
	rows.extend(application_row(application) for application in applications)
	rows.extend(document_rows(applications))

	return rows


def loan_row(loan: dict) -> dict:
	return {
		"title": loan.loan_product,
		"note": _("{0} · {1} outstanding · {2}").format(
			loan.name, money(outstanding_of(loan)), status_label(loan)
		),
		"kind": _("Loan account"),
		"url": loan_url(loan.name),
	}


def application_row(application: dict) -> dict:
	return {
		"title": application["product"],
		"note": "{0} · {1}".format(application["reference"], application["stage"]),
		"kind": _("Application"),
		"url": application["url"],
	}


def document_rows(applications: list[dict]) -> list[dict]:
	# One query for all applications, not applications.document_rows per application.
	# ignore_permissions: child table with no rules; parents are already scoped to this borrower.
	names = [application["name"] for application in applications]
	if not names:
		return []

	return [
		{
			"title": row.document_type or _("Document"),
			"note": _("Attached to {0}").format(row.parent),
			"kind": _("Document"),
			"url": application_url(row.parent),
		}
		for row in frappe.get_all(
			"Loan Application Document",
			filters={"parent": ["in", names], "parenttype": "Loan Application"},
			fields=["parent", "document_type"],
			ignore_permissions=True,
		)
	]


def matches(query: str, rows: list[dict]) -> list[dict]:
	words = query.lower().split()

	return [row for row in rows if all(word in haystack(row) for word in words)]


def haystack(row: dict) -> str:
	return " ".join((row["title"], row["note"], row["kind"])).lower()


def results_note(query: str, total: int, limit: int = RESULT_LIMIT) -> str:
	if not query:
		return ""

	if not total:
		return _("Nothing matches that")

	if total > limit:
		return _("{0} of {1} found · add a word to narrow it").format(limit, total)

	return _("{0} found").format(total)
