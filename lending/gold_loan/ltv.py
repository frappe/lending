# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import cint, flt

from lending.loan_management.doctype.loan_security.loan_security import get_haircut_percentage

METALS = ("Gold", "Silver")
CLOSED_LOAN_STATUSES = ("Closed", "Settled", "Written Off")
GOLD_LOAN_PURPOSES = ("Consumption", "Income Generating")


class GoldLTVSlabs:
	"""RBI LTV slabs for gold and silver consumption loans, chosen by the borrower's total."""

	def __init__(self, rows):
		self.rows = rows

	@classmethod
	def for_product(cls, loan_product):
		if frappe.db.get_value("Loan Product", loan_product, "gold_loan_purpose") != "Consumption":
			return None

		rows = frappe.get_all(
			"Gold LTV Slab",
			filters={"parent": loan_product, "parenttype": "Loan Product"},
			fields=["up_to_amount", "ltv"],
			order_by="idx",
		)
		return cls(rows) if rows else None

	def get_limit(self, value, other_total):
		"""Largest new amount whose LTV fits the slab that the borrower's new total falls in."""
		limit = lower_bound = 0.0
		for row in self.rows:
			candidate = flt(value) * flt(row.ltv) / 100
			if flt(row.up_to_amount):
				candidate = min(candidate, flt(row.up_to_amount) - flt(other_total))

			if flt(other_total) + candidate > lower_bound:
				limit = max(limit, candidate)
			lower_bound = flt(row.up_to_amount)

		return limit

	def get_ltv(self, total):
		for row in self.rows:
			if not flt(row.up_to_amount) or flt(total) <= flt(row.up_to_amount):
				return flt(row.ltv)


def apply_slab_haircut(doc, table):
	"""Lend on the metal lines of a pledge no more than the slab allows."""
	lines = get_metal_lines(doc.get(table))
	if not lines:
		return

	if doc.get("loan"):
		cap = flt(frappe.db.get_value("Loan", doc.loan, "gold_ltv_cap"))
		if cap:
			set_minimum_haircut(lines, 100 - cap)
	else:
		apply_new_loan_slab(doc, lines)

	if doc.doctype == "Loan Security Assignment":
		doc.maximum_loan_value = sum(flt(line.post_haircut_amount) for line in doc.securities)


def set_gold_ltv_cap(loan):
	slabs = GoldLTVSlabs.for_product(loan.loan_product) if loan.is_secured_loan else None
	if not slabs:
		loan.gold_ltv_cap = 0
		return

	other_total = get_borrower_total(
		loan.applicant_type, loan.applicant, exclude_loan=None if loan.is_new() else loan.name
	)
	loan.gold_ltv_cap = slabs.get_ltv(other_total + flt(loan.loan_amount))


def cap_ltv_map(ltv_ratio_map, cap):
	if not flt(cap):
		return ltv_ratio_map

	metal_securities = get_metal_securities(list(ltv_ratio_map))
	return {
		security: min(flt(ltv), flt(cap)) if security in metal_securities else ltv
		for security, ltv in ltv_ratio_map.items()
	}


def cap_haircut_map(haircut_map, cap):
	if not flt(cap):
		return haircut_map

	metal_securities = get_metal_securities(list(haircut_map))
	return {
		security: max(flt(haircut), 100 - flt(cap)) if security in metal_securities else haircut
		for security, haircut in haircut_map.items()
	}


def validate_metal_pledge_has_loan(assignment):
	# The applicant-wise shortfall has no loan, so it could never apply the slab cap
	if not assignment.loan and not assignment.loan_application and get_metal_lines(assignment.securities):
		frappe.throw(_("Gold and silver can be pledged only against a Loan or a Loan Application"))


def validate_credit_assessment(application):
	threshold = flt(frappe.db.get_single_value("Lending Settings", "gold_credit_assessment_above"))
	if not threshold or application.credit_assessment:
		return

	if not get_metal_lines(application.proposed_pledges):
		return

	total = get_borrower_total(
		application.applicant_type, application.applicant, purposes=GOLD_LOAN_PURPOSES
	) + flt(application.loan_amount)
	if total > threshold:
		frappe.throw(
			_(
				"Attach a Credit Assessment. The applicant's total gold and silver loans of {0} are above {1}"
			).format(frappe.format_value(total, "Currency"), frappe.format_value(threshold, "Currency"))
		)


def validate_gold_ltv_slabs(loan_product):
	slabs = loan_product.get("gold_ltv_slabs")
	if not slabs:
		return

	if loan_product.gold_loan_purpose != "Consumption":
		frappe.throw(_("Gold LTV Slabs apply only to a Consumption gold loan product"))

	if flt(slabs[-1].up_to_amount):
		frappe.throw(_("The last Gold LTV Slab must have no Up To Amount"))

	previous_amount = 0.0
	for slab in slabs:
		if not 0 < flt(slab.ltv) <= 100:
			frappe.throw(_("Row {0}: LTV must be above 0 and at most 100").format(slab.idx))

		if slab is slabs[-1]:
			continue

		if flt(slab.up_to_amount) <= previous_amount:
			frappe.throw(_("Row {0}: Up To Amount must be above the previous row's").format(slab.idx))
		previous_amount = flt(slab.up_to_amount)


def apply_new_loan_slab(doc, lines):
	slabs = GoldLTVSlabs.for_product(get_loan_product(doc))
	value = sum(flt(line.amount) for line in lines)
	if not slabs or not value:
		return

	limit = slabs.get_limit(value, get_borrower_total(doc.applicant_type, doc.applicant))
	set_minimum_haircut(lines, 100 * (1 - limit / value))


def set_minimum_haircut(lines, minimum_haircut):
	for line in lines:
		# Start from the security's haircut, not the line's, so a lower slab haircut can take effect again
		line.haircut = max(flt(get_haircut_percentage(line.loan_security)), minimum_haircut)
		# Round first: cint truncates, so 2,49,999.9999 would lose a rupee
		line.post_haircut_amount = cint(flt(flt(line.amount) * (1 - line.haircut / 100), 2))


def get_loan_product(doc):
	if doc.doctype == "Loan Application":
		return doc.loan_product
	return frappe.db.get_value("Loan Application", doc.loan_application, "loan_product")


def get_borrower_total(applicant_type, applicant, exclude_loan=None, purposes=("Consumption",)):
	loan = DocType("Loan")
	loan_product = DocType("Loan Product")

	query = (
		frappe.qb.from_(loan)
		.inner_join(loan_product)
		.on(loan.loan_product == loan_product.name)
		.select(fn.Sum(loan.loan_amount))
		.where(loan.applicant_type == applicant_type)
		.where(loan.applicant == applicant)
		.where(loan.docstatus == 1)
		.where(loan.status.notin(CLOSED_LOAN_STATUSES))
		.where(loan_product.gold_loan_purpose.isin(purposes))
	)
	if exclude_loan:
		query = query.where(loan.name != exclude_loan)

	return flt(query.run()[0][0])


def get_metal_lines(rows):
	metal_securities = get_metal_securities([row.loan_security for row in rows or []])
	return [row for row in rows or [] if row.loan_security in metal_securities]


def get_metal_securities(securities):
	if not securities:
		return set()

	security = DocType("Loan Security")
	security_type = DocType("Loan Security Type")

	return set(
		frappe.qb.from_(security)
		.inner_join(security_type)
		.on(security.loan_security_type == security_type.name)
		.select(security.name)
		.where(security.name.isin(securities))
		.where(security_type.metal.isin(METALS))
		.run(pluck=True)
	)
