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
	rows = doc.get(table)
	lines = get_metal_lines(rows)
	if not lines:
		return

	minimum_haircut = get_minimum_haircut(doc, lines, [row for row in rows if row not in lines])
	if minimum_haircut:
		set_minimum_haircut(lines, minimum_haircut)

	if doc.doctype == "Loan Security Assignment":
		doc.maximum_loan_value = sum(flt(line.post_haircut_amount) for line in doc.securities)


def set_gold_ltv_cap(doc):
	doc.gold_ltv_cap = get_application_cap(doc) or get_slab_ltv(doc)


def get_gold_ltv_cap(loan=None, applicant=None):
	if loan:
		return flt(frappe.db.get_value("Loan", loan, "gold_ltv_cap"))

	# Applicant-wise checks pool every loan's collateral, so the strictest cap applies to all of it
	caps = frappe.get_all(
		"Loan",
		filters={
			"applicant": applicant,
			"docstatus": 1,
			"status": ("not in", CLOSED_LOAN_STATUSES),
			"gold_ltv_cap": (">", 0),
		},
		pluck="gold_ltv_cap",
	)
	return min(flt(cap) for cap in caps) if caps else 0


def cap_ltv_map(ltv_ratio_map, cap, metal_securities=None):
	if not flt(cap):
		return ltv_ratio_map

	if metal_securities is None:
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
		security: get_capped_haircut(security, haircut, cap) if security in metal_securities else haircut
		for security, haircut in haircut_map.items()
	}


def get_capped_haircut(security, haircut, cap):
	# The map holds the security's own haircut only, so fall back to the type's like a pledge does
	return max(flt(haircut) or flt(get_haircut_percentage(security)), 100 - flt(cap))


def validate_metal_pledge_has_loan(assignment):
	# A pledge with neither has no product, so no slab could ever apply to it
	if not assignment.loan and not assignment.loan_application and get_metal_lines(assignment.securities):
		frappe.throw(_("Gold and silver can be pledged only against a Loan or a Loan Application"))


def validate_credit_assessment(doc):
	threshold = flt(frappe.db.get_single_value("Lending Settings", "gold_credit_assessment_above"))
	if not threshold:
		return

	if doc.doctype == "Loan Application":
		loan_doc, lines, assessment = doc, doc.proposed_pledges, doc.credit_assessment
	elif doc.get("loan"):
		loan_doc = frappe.get_doc("Loan", doc.loan)
		# The Loan shows its Credit Assessment field only on a gold product, so ask only there
		if not loan_doc.gold_loan_purpose:
			return
		lines, assessment = doc.securities, get_loan_credit_assessment(loan_doc)
	else:
		return

	if assessment or not get_metal_lines(lines):
		return

	total = get_borrower_total(loan_doc, purposes=GOLD_LOAN_PURPOSES) + flt(loan_doc.loan_amount)
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


def get_minimum_haircut(doc, lines, other_lines):
	if doc.get("loan"):
		cap = get_gold_ltv_cap(doc.loan)
		return 100 - cap if cap else 0

	slabs = GoldLTVSlabs.for_product(get_loan_product(doc))
	value = sum(flt(line.amount) for line in lines)
	if not slabs or not value:
		return 0

	# Lending against the pledge's other collateral is part of this loan, so it moves the slab too
	other_lending = sum(flt(line.post_haircut_amount) for line in other_lines)
	return 100 * (1 - slabs.get_limit(value, get_borrower_total(doc) + other_lending) / value)


def set_minimum_haircut(lines, minimum_haircut):
	for line in lines:
		line.haircut = max(flt(line.haircut) or flt(get_haircut_percentage(line.loan_security)), minimum_haircut)
		# Round first: cint truncates, so 2,49,999.9999 would lose a rupee
		line.post_haircut_amount = cint(flt(flt(line.amount) * (1 - line.haircut / 100), 2))


def get_application_cap(doc):
	if doc.doctype != "Loan" or not doc.loan_application:
		return 0

	application = frappe.db.get_value(
		"Loan Application", doc.loan_application, ["gold_ltv_cap", "loan_amount", "loan_product"], as_dict=True
	)
	# A loan that changed its amount or product may fall in another slab, so it works out its own
	if application.loan_product != doc.loan_product or flt(application.loan_amount) != flt(doc.loan_amount):
		return 0
	return flt(application.gold_ltv_cap)


def get_slab_ltv(doc):
	slabs = GoldLTVSlabs.for_product(doc.loan_product)
	return slabs.get_ltv(get_borrower_total(doc) + flt(doc.loan_amount)) if slabs else 0


def get_loan_credit_assessment(loan):
	if loan.credit_assessment or not loan.loan_application:
		return loan.credit_assessment
	return frappe.db.get_value("Loan Application", loan.loan_application, "credit_assessment")


def get_loan_product(doc):
	if doc.doctype == "Loan Application":
		return doc.loan_product
	return frappe.db.get_value("Loan Application", doc.loan_application, "loan_product")


def get_borrower_total(doc, purposes=("Consumption",)):
	loan = DocType("Loan")
	loan_product = DocType("Loan Product")

	query = (
		frappe.qb.from_(loan)
		.inner_join(loan_product)
		.on(loan.loan_product == loan_product.name)
		.select(fn.Sum(loan.loan_amount))
		.where(loan.company == doc.company)
		.where(loan.applicant_type == doc.applicant_type)
		.where(loan.applicant == doc.applicant)
		.where(loan.docstatus == 1)
		.where(loan.status.notin(CLOSED_LOAN_STATUSES))
		.where(loan_product.gold_loan_purpose.isin(purposes))
	)

	if doc.doctype == "Loan" and not doc.is_new():
		query = query.where(loan.name != doc.name)

	# A loan made from this pledge's application is the pledge itself, not another loan
	loan_application = doc.name if doc.doctype == "Loan Application" else doc.get("loan_application")
	if loan_application:
		query = query.where(fn.Coalesce(loan.loan_application, "") != loan_application)

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
