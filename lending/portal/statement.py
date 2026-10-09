# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

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

PAID_FIELDS = (
	("total_interest_paid", "Interest paid"),
	("principal_amount_paid", "Principal repaid"),
	("total_penalty_paid", "Penalty paid"),
	("total_charges_paid", "Charges paid"),
)


def financial_year(date=None) -> tuple[str, str, str]:
	# The statutory April-March year, not erpnext's configurable Fiscal Year.
	day = getdate(date or nowdate())
	start = day.year if day.month >= 4 else day.year - 1

	return f"{start}-{start + 1}", f"{start}-04-01", f"{start + 1}-03-31"


def requested_year(label: str | None) -> tuple[str, str, str]:
	if not label:
		return financial_year()

	try:
		start = int(str(label).split("-")[0])
	except (ValueError, IndexError):
		return financial_year()

	return f"{start}-{start + 1}", f"{start}-04-01", f"{start + 1}-03-31"


def requested_date(value: str | None, default: str) -> str:
	# Studio fires the data source before its script loads, so a param can arrive as "undefined".
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
	# Filtering the borrower's own list is the ownership check.
	customers = get_portal_customers()
	loans = get_loans(customers) if customers else []

	if loan:
		return customers, [row for row in loans if row.name == loan]

	chosen = chosen_loan(loans)

	return customers, [chosen] if chosen else loans


def loan_groups(loans: list) -> dict:
	# The report takes one company and one applicant at a time.
	groups = {}
	for row in loans:
		company = frappe.db.get_value("Loan", row.name, "company")
		groups.setdefault((company, row.applicant), []).append(row.name)

	return groups


def download_url(method: str, **params) -> str:
	query = urlencode({key: value for key, value in params.items() if value})

	return f"/api/method/lending.portal.downloads.{method}" + (f"?{query}" if query else "")


@frappe.whitelist()
def get_statement_page() -> dict:
	from lending.loan_management.report.loan_statement_of_account.loan_statement_of_account import (
		execute,
	)

	# Imported here: preview builds on this module.
	from lending.portal import preview

	loan = frappe.form_dict.get("loan")
	_label, year_start, _year_end = financial_year()
	from_date = requested_date(frappe.form_dict.get("from_date"), year_start)
	to_date = requested_date(frappe.form_dict.get("to_date"), nowdate())

	if preview.is_preview():
		return preview.statement_page(loan, from_date, to_date)

	customers, loans = owned_loans(loan)
	# From the first loan's start, not from_date: what was owed before the period is its opening balance.
	since = min([getdate(row.posting_date) for row in loans] + [getdate(from_date)])
	entries = []
	for (company, applicant), names in loan_groups(loans).items():
		if not company:
			continue
		_columns, data = execute(
			{
				"company": company,
				"applicant": applicant,
				"applicant_type": "Customer",
				"loan": names[0] if len(names) == 1 else None,
				"from_date": since,
				"to_date": to_date,
			}
		)
		entries.extend(data)

	payload = shell_payload(_("Statement of account"), "", loans)
	payload["head_note"] = _("{0} to {1}").format(long_date(from_date), long_date(to_date))
	payload.update(statement_body(entries, from_date, to_date, len(loans)))
	payload.update(
		{
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


def statement_body(entries: list[dict], from_date: str, to_date: str, accounts: int) -> dict:
	"""Laid out as a bank statement: the opening balance, each entry with the balance after it, the closing."""
	opening, shown = ledger(entries, from_date, to_date)
	accounts_note = _("across 1 account") if accounts == 1 else _("across {0} accounts").format(accounts)
	summary = statement_summary(shown, opening, to_date, accounts_note)

	rows = ([opening_row(opening, from_date)] + [present_entry(row) for row in shown]) if shown or opening else []

	return {
		# A voucher can post several entries, so the index is the key.
		"rows": [dict(row, name=str(index)) for index, row in enumerate(rows)],
		"rows_note": (
			(_("1 entry from {1} to {2}") if len(shown) == 1 else _("{0} entries from {1} to {2}")).format(
				len(shown), short_date(from_date), short_date(to_date)
			)
			if shown
			else _("No entries between {0} and {1}").format(short_date(from_date), short_date(to_date))
		),
		"totals": statement_totals(summary),
		"summary": summary,
	}


def ledger(entries: list[dict], from_date: str, to_date: str) -> tuple[float, list[dict]]:
	"""What was owed before `from_date`, and the entries within the dates with the balance after each."""
	# The report's own running balance starts at zero on its first entry, and per report call.
	entries = sorted(entries, key=lambda row: getdate(row.get("posting_date")))
	start, end = getdate(from_date), getdate(to_date)

	opening = sum(movement(row) for row in entries if getdate(row.get("posting_date")) < start)
	balance, shown = opening, []
	for row in entries:
		if start <= getdate(row.get("posting_date")) <= end:
			balance += movement(row)
			shown.append(dict(row, balance=balance))

	return opening, shown


def movement(row: dict) -> float:
	return flt(row.get("debit")) - flt(row.get("credit"))


def opening_row(opening: float, from_date: str) -> dict:
	return {
		"date": short_date(from_date),
		"label": _("Opening balance"),
		"amount": money(opening),
		"direction": _("Owed"),
		"debit": "—",
		"credit": "—",
		"balance": money(opening),
	}


def present_entry(row: dict) -> dict:
	debit = flt(row.get("debit"))
	credit = flt(row.get("credit"))

	return {
		"date": short_date(row.get("posting_date")),
		"label": row.get("transaction_type") or _("Entry"),
		"amount": money(debit) if debit else money(credit),
		"direction": _("Charged") if debit else _("Paid"),
		"debit": money(debit) if debit else "—",
		"credit": money(credit) if credit else "—",
		"balance": money(row.get("balance")),
	}


def statement_totals(summary: dict) -> list[dict]:
	return [
		{"label": _("Opening balance"), "value": summary["opening"]},
		{"label": _("Charged"), "value": summary["charged"]},
		{"label": _("Paid"), "value": summary["paid"]},
		{"label": _("Closing balance"), "value": summary["balance"]},
	]


def statement_summary(entries: list[dict], opening: float, to_date: str, accounts_note: str) -> dict:
	debit = sum(flt(row.get("debit")) for row in entries)
	credit = sum(flt(row.get("credit")) for row in entries)

	return {
		"opening": money(opening),
		"charged": money(debit),
		"paid": money(credit),
		"balance": money(opening + debit - credit),
		"balance_note": _("As on {0}, {1}").format(short_date(to_date), accounts_note),
	}


@frappe.whitelist()
def get_certificate_page() -> dict:
	"""Amounts paid in a financial year; provisional (paid plus still scheduled) while the year runs."""
	from lending.portal import preview

	if preview.is_preview():
		return preview.certificate_page(frappe.form_dict.get("year"), frappe.form_dict.get("loan"))

	label, start, end = requested_year(frappe.form_dict.get("year"))
	customers, loans = owned_loans(frappe.form_dict.get("loan"))
	names = [row.name for row in loans]

	running = getdate(end) > getdate(nowdate())
	by_loan = amounts_by_loan(names, start, end, running)
	totals = {field: sum(amounts[field] for amounts in by_loan.values()) for field, _title in PAID_FIELDS}

	rows = [
		{"label": _(title), "value": money(totals[field])} for field, title in PAID_FIELDS if totals[field]
	]

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
			# Deliberately no tax figure: the app holds no tax logic to compute one.
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
	other = flt(totals["total_penalty_paid"]) + flt(totals["total_charges_paid"])

	return {
		"interest": money(totals["total_interest_paid"]),
		"principal": money(totals["principal_amount_paid"]),
		"other": money(other) if other else "",
		"total": money(sum(flt(value) for value in totals.values())),
	}


def account_row(loan, amounts: dict) -> dict:
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
	by_loan = {loan: dict.fromkeys((field for field, _title in PAID_FIELDS), 0.0) for loan in loans}

	for loan, field, amount in paid_in_period(loans, start, end):
		by_loan[loan][field] += amount
	if running:
		for loan, field, amount in scheduled_in_period(loans, nowdate(), end):
			by_loan[loan][field] += amount

	return by_loan


def paid_in_period(loans: list[str], start: str, end: str):
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
