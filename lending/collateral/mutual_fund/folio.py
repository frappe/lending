# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import functions as fn
from frappe.utils import flt

PLEDGED_STATUSES = ("Pledged", "Repossessed")


def get_mutual_fund_securities(securities):
	securities = [security for security in securities if security]
	if not securities:
		return set()
	return set(
		frappe.get_all("Loan Security", filters={"name": ("in", securities), "is_mutual_fund": 1}, pluck="name")
	)


def get_folio_balances(
	securities, loan=None, applicant_type=None, applicant=None, exclude=None, for_update=False
):
	"""Units each folio still has pledged, as {(loan_security, holding): units}, oldest pledge first.

	With a loan, only that loan's pledges, releases and sales count. Without one, only the
	applicant's pledges and releases that have no loan.
	"""
	if not securities:
		return {}

	pledge = frappe.qb.DocType("Pledge")
	assignment = frappe.qb.DocType("Loan Security Assignment")
	pledged = (
		frappe.qb.from_(pledge)
		.inner_join(assignment)
		.on(pledge.parent == assignment.name)
		.select(
			pledge.loan_security,
			pledge.mutual_fund_holding,
			fn.Sum(pledge.qty),
			fn.Min(assignment.pledge_time),
		)
		.where(pledge.parenttype == "Loan Security Assignment")
		.where(pledge.loan_security.isin(securities))
		.where(pledge.mutual_fund_holding.isnotnull())
		.where(assignment.docstatus == 1)
		.where(assignment.status.isin(PLEDGED_STATUSES))
		.groupby(pledge.loan_security, pledge.mutual_fund_holding)
	)

	unpledge = frappe.qb.DocType("Unpledge")
	release = frappe.qb.DocType("Loan Security Release")
	released = (
		frappe.qb.from_(unpledge)
		.inner_join(release)
		.on(unpledge.parent == release.name)
		.select(unpledge.loan_security, unpledge.mutual_fund_holding, fn.Sum(unpledge.qty))
		.where(unpledge.loan_security.isin(securities))
		.where(unpledge.mutual_fund_holding.isnotnull())
		.where(release.docstatus == 1)
		.where(release.status == "Approved")
		.groupby(unpledge.loan_security, unpledge.mutual_fund_holding)
	)

	item = frappe.qb.DocType("Loan Security Sale Item")
	sale = frappe.qb.DocType("Loan Security Sale")
	sold = (
		frappe.qb.from_(item)
		.inner_join(sale)
		.on(item.parent == sale.name)
		.select(item.loan_security, item.mutual_fund_holding, fn.Sum(item.sold_qty))
		.where(item.loan_security.isin(securities))
		.where(item.mutual_fund_holding.isnotnull())
		.where(sale.docstatus == 1)
		.groupby(item.loan_security, item.mutual_fund_holding)
	)

	if loan:
		pledged = pledged.where(assignment.loan == loan)
		released = released.where(release.loan == loan)
		sold = sold.where(sale.loan == loan)
	else:
		pledged = pledged.where(assignment.applicant_type == applicant_type).where(
			assignment.applicant == applicant
		)
		pledged = pledged.where(assignment.loan.isnull() | (assignment.loan == ""))
		released = released.where(release.applicant_type == applicant_type).where(
			release.applicant == applicant
		)
		released = released.where(release.loan.isnull() | (release.loan == ""))
		sold = None

	if exclude:
		released = released.where(release.name != exclude)
		if sold is not None:
			sold = sold.where(sale.name != exclude)

	queries = [query for query in (pledged, released, sold) if query is not None]
	if for_update:
		queries = [query.for_update() for query in queries]
	pledged_rows, *taken_rows = (query.run() for query in queries)

	taken = defaultdict(float)
	for rows in taken_rows:
		for security, holding, qty in rows:
			taken[(security, holding)] += flt(qty)

	balances = {}
	for security, holding, qty, _first_pledged in sorted(pledged_rows, key=lambda row: (str(row[3] or ""), row[1])):
		balances[(security, holding)] = max(flt(qty) - taken[(security, holding)], 0)
	return balances


def split_by_folio(doc, table, qty_fields, balances):
	rows = doc.get(table)
	mutual_funds = get_mutual_fund_securities({row.loan_security for row in rows})
	if not any(row.loan_security in mutual_funds and not row.mutual_fund_holding for row in rows):
		return

	taken = defaultdict(float)
	for row in rows:
		if row.mutual_fund_holding:
			taken[(row.loan_security, row.mutual_fund_holding)] += get_row_units(row, qty_fields)

	ordered = []
	for row in list(rows):
		if row.loan_security not in mutual_funds or row.mutual_fund_holding:
			ordered.append(row)
			continue

		left = {fieldname: flt(row.get(fieldname)) for fieldname in qty_fields}
		parts = []
		for (security, holding), balance in balances.items():
			free = balance - taken[(security, holding)]
			if security != row.loan_security or free <= 0 or not has_units(left):
				continue
			part = {fieldname: min(qty, free) for fieldname, qty in left.items()}
			taken[(security, holding)] += max(part.values())
			left = {fieldname: qty - part[fieldname] for fieldname, qty in left.items()}
			parts.append((holding, part))
		# Units no folio has left stay on a row without one, which validate_folio_units reports
		if has_units(left) or not parts:
			parts.append((None, left))

		for index, (holding, part) in enumerate(parts):
			target = row if index == 0 else doc.append(table, row.as_dict(no_default_fields=True))
			target.mutual_fund_holding = holding
			target.update(part)
			ordered.append(target)

	doc.set(table, ordered)
	for idx, row in enumerate(doc.get(table), start=1):
		row.idx = idx


def validate_folio_units(doc, table, qty_fields, balances, title):
	rows = doc.get(table)
	mutual_funds = get_mutual_fund_securities({row.loan_security for row in rows})
	used = defaultdict(float)
	for row in rows:
		if row.loan_security not in mutual_funds:
			continue
		if not row.mutual_fund_holding:
			frappe.throw(
				_("Row {0}: No pledged folio of Loan Security {1} has these units left").format(
					row.idx, frappe.bold(row.loan_security)
				),
				title=title,
			)
		used[(row.loan_security, row.mutual_fund_holding)] += get_row_units(row, qty_fields)

	for (security, holding), units in used.items():
		balance = flt(balances.get((security, holding)))
		if flt(units, 9) > flt(balance, 9):
			frappe.throw(
				_("Mutual Fund Holding {0} has {1} units of Loan Security {2} pledged here, so {3} cannot be taken from it").format(
					frappe.bold(holding), frappe.bold(balance), frappe.bold(security), frappe.bold(units)
				),
				title=title,
			)


def get_row_units(row, qty_fields):
	return max(flt(row.get(fieldname)) for fieldname in qty_fields)


def has_units(qty_by_field):
	return any(flt(qty, 9) > 0 for qty in qty_by_field.values())
