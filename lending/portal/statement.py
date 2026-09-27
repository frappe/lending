# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Read-only data for the borrower's statement of account and interest certificate.

The statement reuses the loan_statement_of_account report rather than growing a second
one, as PORTAL_PLAN.md section 6.9 requires. The report needs a company, and that is
read from the borrower's own loans, never from the request.

The certificate is built from money that actually moved -- submitted Loan Repayment
rows -- not from the schedule, per section 6.10. It reports what the borrower paid and
stops there: no tax figure, no section, no rebate. A wrong number on a document
someone files with their return is a real liability, and the app holds no tax logic to
compute one from.
"""

from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from lending.portal.core import (
	chosen_loan,
	get_loans,
	get_portal_customers,
	long_date,
	money,
	shell_payload,
	short_date,
)

# Loan Repayment carries these four separately, which is exactly the split a borrower's
# accountant needs. Interest and principal answer different sections of the Act.
PAID_FIELDS = (
	("total_interest_paid", "Interest paid"),
	("principal_amount_paid", "Principal repaid"),
	("total_penalty_paid", "Penalty paid"),
	("total_charges_paid", "Charges paid"),
)


def financial_year(date=None) -> tuple[str, str, str]:
	"""The Indian financial year around a date: April to March.

	Not erpnext's Fiscal Year records, which a company may have configured to any
	dates. An interest certificate is an income tax document, so the year it covers is
	fixed by statute, not by configuration.
	"""
	day = getdate(date or nowdate())
	start = day.year if day.month >= 4 else day.year - 1

	return f"{start}-{start + 1}", f"{start}-04-01", f"{start + 1}-03-31"


def requested_year(label: str | None) -> tuple[str, str, str]:
	"""The year the borrower asked for, or the current one."""
	if not label:
		return financial_year()

	try:
		start = int(str(label).split("-")[0])
	except (ValueError, IndexError):
		return financial_year()

	return f"{start}-{start + 1}", f"{start}-04-01", f"{start + 1}-03-31"


def requested_date(value: str | None, default: str) -> str:
	"""The date the borrower asked for, or `default` when there is none to read.

	A Studio page fires its data source once before its script has loaded, and a
	binding to a ref that does not exist yet arrives as the string "undefined". That is
	no reason to fail the page, so anything that is not a date is read as no date.
	"""
	if not value:
		return default

	try:
		return str(getdate(value))
	except frappe.ValidationError:
		return default


def year_options(count: int = 5) -> list[dict]:
	current, _start, _end = financial_year()
	first = int(current.split("-")[0])

	return [
		{"label": f"{year}-{year + 1}", "value": f"{year}-{year + 1}"}
		for year in range(first, first - count, -1)
	]


def owned_loans(loan: str | None = None) -> tuple[list[str], list]:
	"""The borrower's loans, narrowed to one when the request names it, and otherwise to
	the account they chose.

	Narrowing by filtering the borrower's own list is the ownership check: a name that
	is not in it simply matches nothing, so an unowned loan cannot widen the result.
	"""
	customers = get_portal_customers()
	loans = get_loans(customers) if customers else []

	if loan:
		return customers, [row for row in loans if row.name == loan]

	chosen = chosen_loan(loans)

	return customers, [chosen] if chosen else loans


def loan_groups(loans: list) -> dict:
	"""Loans grouped by the company and customer they belong to.

	The report filters on one company and one applicant at a time, and one login can
	hold several customer records, so the statement is assembled per group.
	"""
	groups = {}
	for row in loans:
		company = frappe.db.get_value("Loan", row.name, "company")
		groups.setdefault((company, row.applicant), []).append(row.name)

	return groups


def download_url(method: str, **params) -> str:
	"""Where the page's download link points.

	The filters travel in the link rather than being defaulted again by the download
	endpoint, so a borrower looking at one period downloads that period and not the
	one the page would have opened on.
	"""
	query = urlencode({key: value for key, value in params.items() if value})

	return f"/api/method/lending.portal.downloads.{method}" + (f"?{query}" if query else "")


@frappe.whitelist()
def get_statement_page() -> dict:
	"""Ledger entries across the borrower's loans for a date range."""
	from lending.loan_management.report.loan_statement_of_account.loan_statement_of_account import (
		execute,
	)

	loan = frappe.form_dict.get("loan")
	_label, year_start, _year_end = financial_year()
	from_date = requested_date(frappe.form_dict.get("from_date"), year_start)
	to_date = requested_date(frappe.form_dict.get("to_date"), nowdate())

	customers, loans = owned_loans(loan)
	entries = []
	for (company, applicant), names in loan_groups(loans).items():
		if not company:
			continue
		_columns, data = execute(
			{
				"company": company,
				"applicant": applicant,
				"applicant_type": "Customer",
				# The report reads every loan of the applicant unless told one. A group of
				# one is either all the applicant has or the account the borrower chose.
				"loan": names[0] if len(names) == 1 else None,
				"from_date": from_date,
				"to_date": to_date,
			}
		)
		entries.extend(data)

	entries.sort(key=lambda row: getdate(row.get("posting_date")))
	# A voucher can post more than one entry, so a row's key is its place in the list.
	rows = [dict(present_entry(row), name=str(index)) for index, row in enumerate(entries)]
	accounts_note = (
		_("across 1 account") if len(loans) == 1 else _("across {0} accounts").format(len(loans))
	)
	summary = statement_summary(entries, to_date, accounts_note)

	# No header button on this page -- the download lives inside it, next to the dates
	# it obeys -- so there is no label for one either.
	payload = shell_payload(_("Statement of account"), "", loans)
	# The header says which period is on screen; the generic note would not.
	payload["head_note"] = _("{0} to {1}").format(long_date(from_date), long_date(to_date))
	payload.update(
		{
			"rows": rows,
			"rows_note": (
				(_("1 entry from {1} to {2}") if len(rows) == 1 else _("{0} entries from {1} to {2}")).format(
					len(rows), short_date(from_date), short_date(to_date)
				)
				if rows
				else _("No entries between {0} and {1}").format(
					short_date(from_date), short_date(to_date)
				)
			),
			"totals": statement_totals(summary),
			"summary": summary,
			"totals_note": (
				_("Across 1 account") if len(loans) == 1 else _("Across {0} accounts").format(len(loans))
			),
			"from_date": from_date,
			"to_date": to_date,
			"download_url": download_url(
				"download_statement", from_date=from_date, to_date=to_date, loan=loan
			),
			"download_label": _("Download PDF"),
		}
	)

	return payload


def present_entry(row: dict) -> dict:
	debit = flt(row.get("debit"))
	credit = flt(row.get("credit"))

	# The report's own column name: transaction_type, not the particulars a GL report
	# would use. The voucher and loan names are left out; they mean nothing to a borrower.
	return {
		"date": short_date(row.get("posting_date")),
		"label": row.get("transaction_type") or _("Entry"),
		"amount": money(debit) if debit else money(credit),
		"direction": _("Charged") if debit else _("Paid"),
		# One column each, the way a ledger reads, so an entry's side is where it
		# stands rather than a word beside it. The empty side is a dash, so a blank
		# cell does not read as a figure that failed to load.
		"debit": money(debit) if debit else "—",
		"credit": money(credit) if credit else "—",
		"balance": money(row.get("balance")),
	}


def statement_totals(summary: dict) -> list[dict]:
	"""The summary as labelled rows, which is the shape the PDF prints."""
	return [
		{"label": _("Charged"), "value": summary["charged"]},
		{"label": _("Paid"), "value": summary["paid"]},
		{"label": _("Closing balance"), "value": summary["balance"]},
	]


def statement_summary(entries: list[dict], to_date: str, accounts_note: str) -> dict:
	"""The three totals by name, for a page that sets each in a card of its own."""
	debit = sum(flt(row.get("debit")) for row in entries)
	credit = sum(flt(row.get("credit")) for row in entries)

	return {
		"charged": money(debit),
		"paid": money(credit),
		"balance": money(debit - credit),
		"balance_note": _("As on {0}, {1}").format(short_date(to_date), accounts_note),
	}


@frappe.whitelist()
def get_certificate_page() -> dict:
	"""What the borrower paid in a financial year, split the way their return needs.

	Provisional while the year is still running: paid so far, plus what the schedule
	says is still to come before 31 March. Final once the year has closed, when only
	money that moved is reported.
	"""
	label, start, end = requested_year(frappe.form_dict.get("year"))
	customers, loans = owned_loans(frappe.form_dict.get("loan"))
	names = [row.name for row in loans]

	running = getdate(end) > getdate(nowdate())
	by_loan = amounts_by_loan(names, start, end, running)
	totals = {field: sum(amounts[field] for amounts in by_loan.values()) for field, _title in PAID_FIELDS}

	rows = [
		{"label": _(title), "value": money(totals[field])} for field, title in PAID_FIELDS if totals[field]
	]

	# No header button on this page -- the download lives inside it, under the year it
	# obeys -- so there is no label for one either.
	payload = shell_payload(_("Interest certificate"), "", loans)
	payload["head_note"] = _("Financial year {0} · {1}").format(
		label, _("provisional") if running else _("final")
	)
	payload.update(
		{
			"rows": rows,
			"rows_note": (
				_("Provisional · paid to date plus instalments due before {0}").format(
					long_date(end)
				)
				if running
				else _("Final · amounts paid between {0} and {1}").format(
					long_date(start), long_date(end)
				)
			),
			"year": label,
			"year_label": _("Financial year {0}").format(label),
			"kind": _("Provisional") if running else _("Final"),
			"kind_theme": "orange" if running else "green",
			"summary": certificate_summary(totals),
			"accounts": [account_row(row, by_loan[row.name]) for row in loans],
			"accounts_note": (
				_("1 account covered") if len(loans) == 1 else _("{0} accounts covered").format(len(loans))
			),
			"years": year_options(),
			# No tax figure and no section of the Act. Section 6.10: the certificate
			# reports what was paid, and the borrower's accountant works out the relief.
			"disclaimer": _(
				"This certificate reports amounts paid. It states no tax relief; "
				"please consult your tax adviser."
			),
			"download_url": download_url(
				"download_certificate", year=label, loan=frappe.form_dict.get("loan")
			),
			"download_label": _("Download {0} certificate").format(label),
		}
	)

	return payload


def certificate_summary(totals: dict) -> dict:
	"""The year's figures by name, for a page that sets each in a card of its own.

	Penalty and charges share one card: they are rare, and neither is what a borrower
	opens an interest certificate for.
	"""
	other = flt(totals["total_penalty_paid"]) + flt(totals["total_charges_paid"])

	return {
		"interest": money(totals["total_interest_paid"]),
		"principal": money(totals["principal_amount_paid"]),
		"other": money(other) if other else "",
		"total": money(sum(flt(value) for value in totals.values())),
	}


def account_row(loan, amounts: dict) -> dict:
	"""One loan's share of the year. `label` and `value` are what the PDF prints."""
	return {
		"name": loan.name,
		"label": loan.loan_product,
		"value": loan.name,
		"detail": "",
		"interest": money(amounts["total_interest_paid"]),
		"principal": money(amounts["principal_amount_paid"]),
		"total": money(sum(amounts.values())),
	}


def amounts_by_loan(loans: list[str], start: str, end: str, running: bool) -> dict:
	"""Each loan's amounts for the year: paid, plus what is still scheduled if it is running."""
	by_loan = {loan: dict.fromkeys((field for field, _title in PAID_FIELDS), 0.0) for loan in loans}

	for loan, field, amount in paid_in_period(loans, start, end):
		by_loan[loan][field] += amount
	if running:
		for loan, field, amount in scheduled_in_period(loans, nowdate(), end):
			by_loan[loan][field] += amount

	return by_loan


def paid_in_period(loans: list[str], start: str, end: str):
	"""Money that actually moved, from submitted repayments only, as (loan, field, amount)."""
	if not loans:
		return

	rows = frappe.get_all(
		"Loan Repayment",
		filters={
			"against_loan": ["in", loans],
			"docstatus": 1,
			"posting_date": ["between", [start, end]],
		},
		fields=["against_loan", *(field for field, _title in PAID_FIELDS)],
	)

	for row in rows:
		for field, _title in PAID_FIELDS:
			yield row.against_loan, field, flt(row.get(field))


def scheduled_in_period(loans: list[str], start: str, end: str):
	"""What the schedule still expects before the year closes, as (loan, field, amount)."""
	if not loans:
		return

	loan_of = dict(
		frappe.get_all(
			"Loan Repayment Schedule",
			filters={"loan": ["in", loans], "docstatus": 1, "status": "Active"},
			fields=["name", "loan"],
			as_list=True,
		)
	)
	if not loan_of:
		return

	rows = frappe.get_all(
		"Repayment Schedule",
		filters={
			"parent": ["in", list(loan_of)],
			"parenttype": "Loan Repayment Schedule",
			"payment_date": ["between", [start, end]],
		},
		fields=["parent", "principal_amount", "interest_amount"],
		ignore_permissions=True,
	)

	for row in rows:
		yield loan_of[row.parent], "total_interest_paid", flt(row.interest_amount)
		yield loan_of[row.parent], "principal_amount_paid", flt(row.principal_amount)
