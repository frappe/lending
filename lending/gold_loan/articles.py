# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import cint, flt, getdate, nowdate

from lending.gold_loan.ltv import get_metal_lines, get_metal_securities
from lending.loan_management.doctype.loan_security.loan_security import get_haircut_percentage

OPEN_ASSIGNMENT_STATUSES = ("Pledge Requested", "Pledged")
ASSAY_FIELDS = ("gross_weight", "deduction_weight", "net_weight", "fineness", "defects")


def set_article_lines(assignment):
	"""Value each article at its nearest published purity, and pledge one line per purity."""
	if not assignment.get("articles"):
		return

	for row in assignment.articles:
		validate_article(assignment, row)
		set_article_qty(row)

	set_metal_lines(assignment)
	validate_weight_caps(assignment)


def validate_assay(assignment):
	if not assignment.get("articles"):
		return

	if not assignment.ownership_declaration:
		frappe.throw(_("Attach the applicant's Ownership Declaration before you submit"))

	if not assignment.borrower_present_at_assay:
		frappe.throw(_("The borrower must be present at the assay. Check Borrower Present at Assay before you submit"))


def validate_lien_references(assignment):
	for line in get_metal_lines(assignment.securities):
		if not line.lien_reference and tracks_lien(line.loan_security_type):
			frappe.throw(
				_("Row {0}: Enter the packet number in Lien Reference, because Loan Security Type {1} tracks liens").format(
					line.idx, frappe.bold(line.loan_security_type)
				)
			)


def pledge_articles(assignment):
	"""Mark the articles Pledged on this assignment. Runs again when a packet number changes."""
	if assignment.status not in OPEN_ASSIGNMENT_STATUSES:
		return

	packet_numbers = {line.loan_security: line.lien_reference for line in assignment.securities}
	for row in assignment.get("articles"):
		if row.status not in (None, "", "Pledged"):
			continue

		row.status = "Pledged"
		frappe.db.set_value("Pledged Article", row.name, "status", "Pledged", update_modified=False)

		values = {
			"status": "Pledged",
			"current_assignment": assignment.name,
			"packet_number": packet_numbers.get(row.loan_security),
		}
		if frappe.db.get_value("Gold Article", row.gold_article, "current_assignment") != assignment.name:
			values.update({fieldname: row.get(fieldname) for fieldname in ASSAY_FIELDS}, assayed_on=nowdate())
		frappe.db.set_value("Gold Article", row.gold_article, values)


def restore_articles(assignment):
	for row in assignment.get("articles"):
		if frappe.db.get_value("Gold Article", row.gold_article, "current_assignment") == assignment.name:
			frappe.db.set_value("Gold Article", row.gold_article, get_previous_state(row.gold_article, assignment.name))


def validate_release_references(release):
	for line in get_metal_lines(release.securities):
		if not line.release_reference and tracks_lien(line.loan_security_type):
			frappe.throw(
				_("Row {0}: Enter the handover receipt number in Release Reference, because Loan Security Type {1} tracks liens").format(
					line.idx, frappe.bold(line.loan_security_type)
				)
			)


def release_articles(release):
	"""Return the articles once all the gold and silver of the loan is released."""
	from lending.loan_management.doctype.loan_security_release.loan_security_release import (
		get_pledged_security_qty,
	)

	if not get_metal_lines(release.securities):
		return

	if release.loan:
		remaining = get_pledged_security_qty(loan=release.loan)
	else:
		remaining = get_pledged_security_qty(applicant=release.applicant)

	if any(flt(remaining[security], 3) > 0 for security in get_metal_securities(list(remaining))):
		return

	for row in get_pledged_rows(release):
		frappe.db.set_value(
			"Pledged Article",
			row.name,
			{"status": "Released", "released_or_sold_in_type": release.doctype, "released_or_sold_in": release.name},
			update_modified=False,
		)
		frappe.db.set_value(
			"Gold Article", row.gold_article, {"status": "Released", "current_assignment": None, "packet_number": None}
		)


def restore_released_articles(release):
	rows = frappe.get_all(
		"Pledged Article",
		filters={"released_or_sold_in_type": release.doctype, "released_or_sold_in": release.name},
		fields=["name", "parent", "gold_article", "loan_security"],
	)
	for row in rows:
		frappe.db.set_value(
			"Pledged Article",
			row.name,
			{"status": "Pledged", "released_or_sold_in_type": None, "released_or_sold_in": None},
			update_modified=False,
		)
		frappe.db.set_value(
			"Gold Article",
			row.gold_article,
			{
				"status": "Pledged",
				"current_assignment": row.parent,
				"packet_number": frappe.db.get_value(
					"Pledge", {"parent": row.parent, "loan_security": row.loan_security}, "lien_reference"
				),
			},
		)


def validate_article(assignment, row):
	if [article.gold_article for article in assignment.articles].count(row.gold_article) > 1:
		frappe.throw(_("Row {0}: Gold Article {1} is added more than once").format(row.idx, frappe.bold(row.gold_article)))

	article = frappe.db.get_value(
		"Gold Article",
		row.gold_article,
		["applicant_type", "applicant", "status", "metal", "article_kind", "gross_weight", "deduction_weight", "fineness"],
		as_dict=True,
	)
	if (article.applicant_type, article.applicant) != (assignment.applicant_type, assignment.applicant):
		frappe.throw(_("Row {0}: Gold Article {1} belongs to another applicant").format(row.idx, frappe.bold(row.gold_article)))

	if article.status == "Sold":
		frappe.throw(_("Row {0}: Gold Article {1} has been sold").format(row.idx, frappe.bold(row.gold_article)))

	other_assignment = get_open_assignment(row.gold_article, assignment.name)
	if other_assignment:
		frappe.throw(
			_("Row {0}: Gold Article {1} is already pledged on Loan Security Assignment {2}").format(
				row.idx, frappe.bold(row.gold_article), frappe.bold(other_assignment)
			)
		)

	row.metal, row.article_kind = article.metal, article.article_kind
	# A new row starts from the article's last assay, and staff correct it
	if not flt(row.gross_weight):
		row.gross_weight, row.deduction_weight = article.gross_weight, article.deduction_weight
	if not cint(row.fineness):
		row.fineness = article.fineness


def set_article_qty(row):
	if flt(row.gross_weight) <= 0:
		frappe.throw(_("Row {0}: Enter the gross weight of Gold Article {1}").format(row.idx, frappe.bold(row.gold_article)))

	if flt(row.deduction_weight) > flt(row.gross_weight):
		frappe.throw(_("Row {0}: Deduction weight cannot be more than the gross weight").format(row.idx))

	if not 0 < cint(row.fineness) <= 1000:
		frappe.throw(_("Row {0}: Fineness must be above 0 and at most 1,000").format(row.idx))

	security = get_nearest_purity(row.metal, cint(row.fineness))
	if not security:
		frappe.throw(_("Set the fineness of each published {0} purity in its Loan Security").format(_(row.metal)))

	row.net_weight = flt(flt(row.gross_weight) - flt(row.deduction_weight), row.precision("net_weight"))
	row.loan_security = security.name
	row.qty = flt(row.net_weight * cint(row.fineness) / security.fineness, row.precision("qty"))


def set_metal_lines(assignment):
	qty_by_security = {}
	for row in assignment.articles:
		qty_by_security[row.loan_security] = flt(qty_by_security.get(row.loan_security)) + flt(row.qty)

	metal_lines = {line.loan_security: line for line in get_metal_lines(assignment.securities)}
	lines = [line for line in assignment.securities if line.loan_security not in metal_lines]

	precision = assignment.articles[0].precision("qty")
	for security, qty in qty_by_security.items():
		line = metal_lines.get(security) or frappe._dict(
			loan_security=security,
			haircut=get_haircut_percentage(security),
			**frappe.db.get_value(
				"Loan Security", security, ["loan_security_type", "loan_security_name"], as_dict=True
			),
		)
		line.qty = flt(qty, precision)
		lines.append(line)

	assignment.set("securities", lines)
	for idx, line in enumerate(assignment.securities, 1):
		line.idx = idx


def validate_weight_caps(assignment):
	caps = get_weight_caps(assignment)
	if not caps:
		return

	weights = get_pledged_weights(assignment)
	for row in assignment.articles:
		key = (row.metal, row.article_kind)
		weights[key] = flt(weights.get(key)) + flt(row.gross_weight)

	for (metal, kind), cap in caps.items():
		if flt(weights.get((metal, kind)), 3) > cap:
			frappe.throw(
				_("The applicant's {0} {1} weight of {2} g is above the cap of {3} g").format(
					_(metal), _(kind), flt(weights[(metal, kind)], 3), cap
				),
				title=_("Weight Cap"),
			)


def get_weight_caps(assignment):
	caps = {}
	for row in assignment.articles:
		security_type = frappe.db.get_value("Loan Security", row.loan_security, "loan_security_type")
		fieldname = "max_coin_weight" if row.article_kind == "Coin" else "max_ornament_weight"
		cap = flt(frappe.db.get_value("Loan Security Type", security_type, fieldname))
		if cap:
			key = (row.metal, row.article_kind)
			caps[key] = min(caps.get(key, cap), cap)
	return caps


def get_pledged_weights(assignment):
	"""Gross weight of the applicant's articles on their other open assignments."""
	article = DocType("Pledged Article")
	lsa = DocType("Loan Security Assignment")

	rows = (
		open_article_rows(article, lsa)
		.select(article.metal, article.article_kind, fn.Sum(article.gross_weight))
		.where(lsa.applicant_type == assignment.applicant_type)
		.where(lsa.applicant == assignment.applicant)
		.where(lsa.name != assignment.name)
		.groupby(article.metal, article.article_kind)
		.run()
	)
	return {(metal, kind): flt(weight) for metal, kind, weight in rows}


def get_open_assignment(gold_article, assignment):
	article = DocType("Pledged Article")
	lsa = DocType("Loan Security Assignment")

	rows = (
		open_article_rows(article, lsa)
		.select(lsa.name)
		.where(article.gold_article == gold_article)
		.where(lsa.name != assignment)
		.limit(1)
		.run(pluck=True)
	)
	return rows[0] if rows else None


def get_pledged_rows(release):
	article = DocType("Pledged Article")
	lsa = DocType("Loan Security Assignment")

	query = (
		open_article_rows(article, lsa)
		.select(article.name, article.gold_article)
		.where(lsa.status == "Pledged")
	)
	if release.loan:
		query = query.where(lsa.loan == release.loan)
	else:
		query = query.where(lsa.applicant_type == release.applicant_type).where(lsa.applicant == release.applicant)

	return query.run(as_dict=True)


def open_article_rows(article, lsa):
	# The assignment keeps its status after a release, so the row's own status tells a returned article
	return (
		frappe.qb.from_(article)
		.inner_join(lsa)
		.on(article.parent == lsa.name)
		.where(article.parenttype == "Loan Security Assignment")
		.where(lsa.docstatus == 1)
		.where(lsa.status.isin(OPEN_ASSIGNMENT_STATUSES))
		.where(fn.Coalesce(article.status, "").isin(["", "Pledged"]))
	)


def get_nearest_purity(metal, fineness):
	security = DocType("Loan Security")
	security_type = DocType("Loan Security Type")

	purities = (
		frappe.qb.from_(security)
		.inner_join(security_type)
		.on(security.loan_security_type == security_type.name)
		.select(security.name, security.fineness)
		.where(security_type.metal == metal)
		.where(security_type.disabled == 0)
		.where(security.disabled == 0)
		.where(security.fineness > 0)
		.run(as_dict=True)
	)
	return min(purities, key=lambda purity: (abs(purity.fineness - fineness), purity.fineness), default=None)


def get_previous_state(gold_article, assignment):
	"""The article as its last other submitted pledge left it, or as new if there is none."""
	article = DocType("Pledged Article")
	lsa = DocType("Loan Security Assignment")

	previous = (
		frappe.qb.from_(article)
		.inner_join(lsa)
		.on(article.parent == lsa.name)
		.select(article.status, lsa.pledge_time, lsa.creation, *[article[fieldname] for fieldname in ASSAY_FIELDS])
		.where(article.parenttype == "Loan Security Assignment")
		.where(article.gold_article == gold_article)
		.where(lsa.docstatus == 1)
		.where(lsa.name != assignment)
		.orderby(lsa.creation, order=frappe.qb.desc)
		.limit(1)
		.run(as_dict=True)
	)

	state = {"current_assignment": None, "packet_number": None}
	if not previous:
		return {**state, "status": "Available", "assayed_on": None, "defects": None, **dict.fromkeys(ASSAY_FIELDS[:4], 0)}

	previous = previous[0]
	return {
		**state,
		"status": "Sold" if previous.status == "Sold" else "Released",
		"assayed_on": getdate(previous.pledge_time or previous.creation),
		**{fieldname: previous[fieldname] for fieldname in ASSAY_FIELDS},
	}


def tracks_lien(loan_security_type):
	return cint(frappe.db.get_value("Loan Security Type", loan_security_type, "track_lien"))
