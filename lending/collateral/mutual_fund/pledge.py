# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import functions as fn
from frappe.utils import add_days, cint, flt, formatdate, getdate, nowdate

from lending.collateral.doctype.mutual_fund_holding.mutual_fund_holding import get_pledged_units


def validate_mutual_fund_lines(doc):
	# Details stay optional only while a submitted pledge waits as Pledge Requested for its loan
	validate_lines(doc, require_details=doc.docstatus == 1 and doc.status != "Pledge Requested")


def validate_direct_pledge(doc):
	# A pledge from a Loan Application is submitted as Pledge Requested in one step, so the loan checks it instead
	if not doc.loan_application:
		validate_lines(doc, require_details=True)


def validate_application_pledge(loan_security_assignment):
	assignment = frappe.get_doc("Loan Security Assignment", loan_security_assignment)
	validate_lines(
		assignment,
		require_details=True,
		title=_("Loan Security Assignment {0}").format(loan_security_assignment),
	)


def update_securities(doc):
	if not doc.has_value_changed("is_mutual_fund"):
		return
	security = frappe.qb.DocType("Loan Security")
	(
		frappe.qb.update(security)
		.set(security.is_mutual_fund, doc.is_mutual_fund)
		.where(security.loan_security_type == doc.name)
	).run()


def validate_lines(doc, require_details=False, title=None):
	lock_in_map = get_mutual_fund_lock_in([row.loan_security for row in doc.securities])
	pledge_date = getdate(doc.pledge_time or nowdate())
	units_by_holding = defaultdict(float)
	for row in doc.securities:
		if row.loan_security not in lock_in_map:
			continue
		lock_in_days = lock_in_map[row.loan_security]
		if require_details:
			validate_details(row, lock_in_days, title)
		if row.mutual_fund_holding:
			validate_holding(doc, row, title)
			units_by_holding[row.mutual_fund_holding] += flt(row.qty)
		validate_lock_in(row, lock_in_days, pledge_date, title)

	for holding, units in units_by_holding.items():
		validate_units_held(doc, holding, units, title)


def validate_details(row, lock_in_days, title):
	required = ["mutual_fund_holding"] + (["purchase_date"] if lock_in_days else [])
	for fieldname in required:
		if not row.get(fieldname):
			frappe.throw(
				_("Row {0}: Enter the {1} of Loan Security {2}").format(
					row.idx, frappe.bold(_(row.meta.get_label(fieldname))), frappe.bold(row.loan_security)
				),
				title=title,
			)


def validate_holding(doc, row, title):
	holding = frappe.db.get_value(
		"Mutual Fund Holding",
		row.mutual_fund_holding,
		["applicant_type", "applicant", "loan_security"],
		as_dict=True,
	)
	if (holding.applicant_type, holding.applicant) != (doc.applicant_type, doc.applicant):
		frappe.throw(
			_("Row {0}: Mutual Fund Holding {1} belongs to another applicant").format(
				row.idx, frappe.bold(row.mutual_fund_holding)
			),
			title=title,
		)
	if holding.loan_security != row.loan_security:
		frappe.throw(
			_("Row {0}: Mutual Fund Holding {1} holds {2}, not {3}").format(
				row.idx,
				frappe.bold(row.mutual_fund_holding),
				frappe.bold(holding.loan_security),
				frappe.bold(row.loan_security),
			),
			title=title,
		)


def validate_units_held(doc, holding, units, title):
	# The lock makes a second pledge of this folio wait, so both cannot count the same free units
	units_held = flt(frappe.db.get_value("Mutual Fund Holding", holding, "units_held", for_update=True))
	if not units_held:
		return
	pledged_elsewhere = get_pledged_units(holding, exclude_assignment=doc.name)
	# While a draft is being submitted, its saved copy is still a draft and counts nowhere yet
	if not doc.is_new() and frappe.db.get_value(doc.doctype, doc.name, "docstatus") == 1:
		units = get_remaining_units(doc, holding, units, pledged_elsewhere)
	if pledged_elsewhere + units > units_held:
		frappe.throw(
			_(
				"Mutual Fund Holding {0} has {1} units, and {2} are already pledged on other loans. This pledge can take at most {3}"
			).format(
				frappe.bold(holding),
				frappe.bold(units_held),
				frappe.bold(pledged_elsewhere),
				frappe.bold(max(units_held - pledged_elsewhere, 0)),
			),
			title=title,
		)


def validate_lock_in(row, lock_in_days, pledge_date, title):
	if not (lock_in_days and row.purchase_date):
		return
	lock_in_ends = add_days(getdate(row.purchase_date), lock_in_days)
	if lock_in_ends > pledge_date:
		frappe.throw(
			_("Row {0}: These units of Loan Security {1} are locked in until {2} and cannot be pledged before then").format(
				row.idx, frappe.bold(row.loan_security), frappe.bold(formatdate(lock_in_ends))
			),
			title=title,
		)


def get_remaining_units(doc, holding, units, pledged_elsewhere):
	"""Units a submitted pledge still holds of the folio, after its releases and sales.

	Lines linked to the holding in this save but not yet in the database count in full.
	"""
	pledge = frappe.qb.DocType("Pledge")
	saved_units = flt(
		(
			frappe.qb.from_(pledge)
			.select(fn.Sum(pledge.qty))
			.where(pledge.parent == doc.name)
			.where(pledge.parenttype == doc.doctype)
			.where(pledge.mutual_fund_holding == holding)
		).run()[0][0]
	)
	remaining = get_pledged_units(holding) - pledged_elsewhere
	return remaining + max(units - saved_units, 0)


def get_mutual_fund_lock_in(securities):
	if not securities:
		return {}
	security = frappe.qb.DocType("Loan Security")
	security_type = frappe.qb.DocType("Loan Security Type")
	rows = (
		frappe.qb.from_(security)
		.inner_join(security_type)
		.on(security.loan_security_type == security_type.name)
		.select(security.name, security.lock_in_days)
		.where(security.name.isin(securities))
		.where(security_type.is_mutual_fund == 1)
		.run(as_dict=True)
	)
	return {row.name: cint(row.lock_in_days) for row in rows}
