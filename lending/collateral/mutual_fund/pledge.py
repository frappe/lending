# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, cint, formatdate, getdate, nowdate

JOINT_HOLDINGS = ("Joint", "Anyone or Survivor")
REQUIRED_FIELDS = ("folio_number", "holding_mode", "holding_type")


def validate_mutual_fund_lines(doc):
	# Details stay optional only while a submitted pledge waits as Pledge Requested for its loan
	validate_lines(doc, require_details=doc.docstatus == 1 and doc.status != "Pledge Requested")


def validate_direct_pledge(doc):
	# A pledge from a Loan Application is submitted as Pledge Requested in one step, so the loan checks it instead
	if not doc.loan_application:
		validate_lines(doc, require_details=True)


def validate_application_pledge(loan_security_assignment):
	"""Units pledged through a Loan Application become Pledged when the loan is submitted."""
	assignment = frappe.get_doc("Loan Security Assignment", loan_security_assignment)
	validate_lines(
		assignment,
		require_details=True,
		title=_("Loan Security Assignment {0}").format(loan_security_assignment),
	)


def update_securities(doc):
	"""Copy Is Mutual Fund to the type's securities, which only fetch it when they are saved."""
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
	for row in doc.securities:
		if row.loan_security not in lock_in_map:
			continue
		lock_in_days = lock_in_map[row.loan_security]
		if require_details:
			validate_details(row, lock_in_days, title)
		validate_holding(row, title)
		validate_lock_in(row, lock_in_days, pledge_date, title)


def validate_details(row, lock_in_days, title):
	required = list(REQUIRED_FIELDS) + (["purchase_date"] if lock_in_days else [])
	for fieldname in required:
		if not row.get(fieldname):
			frappe.throw(
				_("Row {0}: Enter the {1} of Loan Security {2}").format(
					row.idx, frappe.bold(_(row.meta.get_label(fieldname))), frappe.bold(row.loan_security)
				),
				title=title,
			)


def validate_holding(row, title):
	if row.holding_type == "Minor":
		frappe.throw(
			_("Row {0}: Units in a minor's folio cannot be pledged").format(row.idx),
			title=title,
		)
	if row.holding_type in JOINT_HOLDINGS and not row.all_holders_signed:
		frappe.throw(
			_(
				"Row {0}: Every holder of folio {1} must sign the lien. Tick All Holders Signed the Lien once they have"
			).format(row.idx, frappe.bold(row.folio_number or "")),
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


def get_mutual_fund_lock_in(securities):
	"""Map each mutual fund security to its lock-in days. Other securities are left out."""
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
