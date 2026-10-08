# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re
from difflib import SequenceMatcher

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import add_days, add_months, flt, getdate, nowdate

MONTHS = [
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
]
RC_NAME_MATCH_THRESHOLD = 0.85
OPEN_PDD_STATUSES = ("Pending", "Overdue")


def is_fixed_valuation_security(loan_security):
	loan_security_type = frappe.db.get_value("Loan Security", loan_security, "loan_security_type")
	return (
		frappe.db.get_value("Loan Security Type", loan_security_type, "valuation_method") == "Fixed Valuation"
	)


def get_fixed_security_value(loan_security):
	if is_fixed_valuation_security(loan_security):
		return flt(frappe.db.get_value("Loan Security", loan_security, "original_security_value"))


def get_fixed_security_eligible_value(loan_security):
	if not is_fixed_valuation_security(loan_security):
		return None

	pledge = DocType("Pledge")
	assignment = DocType("Loan Security Assignment")
	row = (
		frappe.qb.from_(pledge)
		.inner_join(assignment)
		.on(pledge.parent == assignment.name)
		.select(pledge.post_haircut_amount, pledge.qty)
		.where(pledge.loan_security == loan_security)
		.where(assignment.docstatus == 1)
		.where(assignment.status == "Pledged")
		.orderby(assignment.creation, order=frappe.qb.desc)
		.limit(1)
	).run(as_dict=True)

	if not row or not flt(row[0].qty):
		return 0.0

	return flt(row[0].post_haircut_amount) / flt(row[0].qty)


def get_loan_vehicles(loan):
	pledge = DocType("Pledge")
	assignment = DocType("Loan Security Assignment")
	loan_security = DocType("Loan Security")

	return (
		frappe.qb.from_(pledge)
		.inner_join(assignment)
		.on(pledge.parent == assignment.name)
		.inner_join(loan_security)
		.on(pledge.loan_security == loan_security.name)
		.select(loan_security.vehicle)
		.distinct()
		.where(assignment.loan == loan)
		.where(assignment.docstatus == 1)
		.where(assignment.status == "Pledged")
		.where(loan_security.vehicle.isnotnull())
	).run(pluck=True)


def get_vehicles_for_securities(securities):
	if not securities:
		return []

	return frappe.get_all(
		"Loan Security",
		filters={"name": ("in", securities), "vehicle": ("is", "set")},
		pluck="vehicle",
	)


def get_assignment_vehicles(loan_security_assignment):
	return get_vehicles_for_securities(
		frappe.get_all("Pledge", filters={"parent": loan_security_assignment}, pluck="loan_security")
	)


def get_vehicle_age_in_years(vehicle, on_date):
	on_date = getdate(on_date)
	month = MONTHS.index(vehicle.manufacturing_month) + 1
	months = (on_date.year - vehicle.manufacturing_year) * 12 + on_date.month - month
	return months / 12


def get_ltv_rule(loan_product, vehicle):
	rules = [
		rule
		for rule in loan_product.get("vehicle_ltv_rules")
		if rule.asset_condition == vehicle.asset_condition
		and (not rule.segment or rule.segment == vehicle.segment)
	]
	rules.sort(key=lambda rule: 0 if rule.segment else 1)
	return rules[0] if rules else None


def normalise_name(name):
	return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", (name or "").casefold())).strip()


def get_application_vehicle_rows(doc):
	vehicle_rows = []
	for row in doc.get("proposed_pledges"):
		if row.vehicle:
			row.loan_security = frappe.db.get_value("Loan Vehicle", row.vehicle, "loan_security")
		elif row.loan_security:
			row.vehicle = frappe.db.get_value("Loan Security", row.loan_security, "vehicle")

		if row.vehicle:
			vehicle_rows.append(row)

	return vehicle_rows


def validate_loan_application(doc):
	vehicle_rows = get_application_vehicle_rows(doc)
	if not vehicle_rows:
		return

	context = get_vehicle_rule_context("Loan Application", doc.name, doc)
	validate_vehicle_count(len(vehicle_rows), context)

	for row in vehicle_rows:
		apply_vehicle_rule(row, get_proposed_vehicle(row), context)


def validate_loan_application_approval(doc):
	if doc.status != "Approved":
		return

	vehicle_rows = [row for row in doc.get("proposed_pledges") if row.vehicle]
	if not vehicle_rows:
		return

	context = get_vehicle_rule_context("Loan Application", doc.name, doc)
	for row in vehicle_rows:
		vehicle = frappe.get_doc("Loan Vehicle", row.vehicle)
		validate_vehicle_for_approval(row, vehicle, get_ltv_rule(context.loan_product, vehicle), context)


def validate_assignment_vehicles(doc):
	vehicle_rows = []
	for row in doc.get("securities"):
		row.vehicle = row.loan_security and frappe.db.get_value("Loan Security", row.loan_security, "vehicle")
		if row.vehicle:
			vehicle_rows.append(row)

	if not vehicle_rows:
		return

	if doc.loan:
		context = get_vehicle_rule_context("Loan", doc.loan)
	elif doc.loan_application:
		context = get_vehicle_rule_context("Loan Application", doc.loan_application)
	else:
		frappe.throw(_("A vehicle can only be pledged against a Loan or a Loan Application"))

	pledged_vehicles = set(get_loan_vehicles(doc.loan)) if doc.loan else set()
	validate_vehicle_count(len(pledged_vehicles | {row.vehicle for row in vehicle_rows}), context)

	for row in vehicle_rows:
		vehicle = get_proposed_vehicle(row)
		rule = apply_vehicle_rule(row, vehicle, context)
		validate_vehicle_for_approval(row, vehicle, rule, context)


def get_vehicle_rule_context(doctype, name, doc=None):
	values = doc or frappe.db.get_value(
		doctype,
		name,
		["loan_product", "posting_date", "repayment_periods", "applicant_name"],
		as_dict=1,
	)
	return frappe._dict(
		loan_product=frappe.get_cached_doc("Loan Product", values.loan_product),
		posting_date=getdate(values.posting_date),
		repayment_periods=values.repayment_periods,
		applicant_name=values.get("applicant_name"),
	)


def validate_vehicle_count(count, context):
	max_vehicles = context.loan_product.max_vehicles_per_loan or 1
	if count > max_vehicles:
		frappe.throw(
			_("Loan Product {0} allows at most {1} vehicle(s) per loan").format(
				frappe.bold(context.loan_product.name), max_vehicles
			)
		)


def get_proposed_vehicle(row):
	vehicle = frappe.get_doc("Loan Vehicle", row.vehicle)
	if vehicle.status in ("Financed", "Repossessed"):
		frappe.throw(
			_("Row {0}: Vehicle {1} is already financed under Loan {2}").format(
				row.idx, frappe.bold(vehicle.name), frappe.bold(vehicle.current_loan)
			)
		)

	if vehicle.status != "Proposed":
		frappe.throw(
			_("Row {0}: Vehicle {1} is {2}. Only a Proposed vehicle can be added.").format(
				row.idx, frappe.bold(vehicle.name), vehicle.status
			)
		)

	return vehicle


def apply_vehicle_rule(row, vehicle, context):
	rule = get_ltv_rule(context.loan_product, vehicle)
	if not rule:
		frappe.throw(
			_("Row {0}: Loan Product {1} has no LTV rule for a {2} {3} vehicle").format(
				row.idx, frappe.bold(context.loan_product.name), vehicle.asset_condition, vehicle.segment
			)
		)

	if not vehicle.asset_value:
		frappe.throw(
			_("Row {0}: Vehicle {1} has no asset value. Set the invoice value or submit a valuation.").format(
				row.idx, frappe.bold(vehicle.name)
			)
		)

	row.qty = 1
	row.loan_security_price = vehicle.asset_value
	row.haircut = 100 - flt(rule.max_ltv_percent)
	return rule


def validate_vehicle_for_approval(row, vehicle, rule, context):
	if rule.max_age_at_sanction_years:
		age = get_vehicle_age_in_years(vehicle, context.posting_date)
		if age > rule.max_age_at_sanction_years:
			frappe.throw(
				_("Row {0}: Vehicle {1} is {2} years old, above the {3} year limit at sanction").format(
					row.idx, frappe.bold(vehicle.name), flt(age, 1), rule.max_age_at_sanction_years
				)
			)

	if rule.max_age_at_maturity_years and context.repayment_periods:
		maturity_date = add_months(context.posting_date, context.repayment_periods)
		age = get_vehicle_age_in_years(vehicle, maturity_date)
		if age > rule.max_age_at_maturity_years:
			frappe.throw(
				_("Row {0}: Vehicle {1} will be {2} years old at maturity, above the {3} year limit").format(
					row.idx, frappe.bold(vehicle.name), flt(age, 1), rule.max_age_at_maturity_years
				)
			)

	if vehicle.asset_condition != "New":
		validity_days = context.loan_product.valuation_validity_days or 90
		valuation_date = vehicle.valuation and frappe.db.get_value(
			"Vehicle Valuation", vehicle.valuation, "valuation_date"
		)
		if not valuation_date or getdate(valuation_date) < getdate(add_days(nowdate(), -validity_days)):
			frappe.throw(
				_("Row {0}: Vehicle {1} needs a valuation from the last {2} days").format(
					row.idx, frappe.bold(vehicle.name), validity_days
				)
			)

	validate_rc_owner_name(context, row, vehicle)


def validate_rc_owner_name(context, row, vehicle):
	applicant_name = context.applicant_name or vehicle.applicant_name
	if not vehicle.rc_owner_name or not applicant_name:
		return

	ratio = SequenceMatcher(
		None, normalise_name(vehicle.rc_owner_name), normalise_name(applicant_name)
	).ratio()
	if ratio >= RC_NAME_MATCH_THRESHOLD:
		return

	message = _("Row {0}: RC owner {1} does not match applicant {2}").format(
		row.idx, frappe.bold(vehicle.rc_owner_name), frappe.bold(applicant_name)
	)
	if frappe.db.get_single_value("Lending Settings", "block_on_rc_owner_name_mismatch"):
		frappe.throw(message, title=_("RC Owner Mismatch"))

	frappe.msgprint(message, title=_("RC Owner Mismatch"), indicator="orange")


def mark_vehicles_financed(loan_security_assignment, loan):
	company = frappe.db.get_value("Loan", loan, "company")
	for vehicle in get_assignment_vehicles(loan_security_assignment):
		values = {"status": "Financed", "current_loan": loan}
		if not frappe.db.get_value("Loan Vehicle", vehicle, "hypothecated_to"):
			values["hypothecated_to"] = company
		frappe.db.set_value("Loan Vehicle", vehicle, values)


def revert_vehicles_to_proposed(loan_security_assignment):
	for vehicle in get_assignment_vehicles(loan_security_assignment):
		frappe.db.set_value("Loan Vehicle", vehicle, {"status": "Proposed", "current_loan": None})


def update_vehicles_on_security_release(doc, cancel=False):
	from lending.loan_management.doctype.loan_security_release.loan_security_release import (
		get_pledged_security_qty,
	)

	if not doc.loan:
		return

	securities = [row.loan_security for row in doc.securities]
	if cancel:
		restore_released_assignments(doc.loan, securities)

	pledged_qty = get_pledged_security_qty(loan=doc.loan)
	vehicles = frappe.get_all(
		"Loan Security",
		filters={"name": ("in", securities), "vehicle": ("is", "set")},
		fields=["name", "vehicle"],
	)

	for row in vehicles:
		vehicle = frappe.db.get_value(
			"Loan Vehicle", row.vehicle, ["name", "status", "hypothecation_status"], as_dict=1
		)
		if cancel:
			if vehicle.status == "Released" and flt(pledged_qty.get(row.name)) > 0:
				values = {"status": "Financed", "noc_issued_on": None, "noc_issued_by": None}
				if vehicle.hypothecation_status == "Termination Requested":
					values["hypothecation_status"] = "Endorsed"
				frappe.db.set_value("Loan Vehicle", vehicle.name, values)
		elif vehicle.status == "Financed" and flt(pledged_qty.get(row.name)) <= 0:
			values = {"status": "Released"}
			if vehicle.hypothecation_status == "Endorsed":
				values["hypothecation_status"] = "Termination Requested"
			frappe.db.set_value("Loan Vehicle", vehicle.name, values)


def restore_released_assignments(loan, securities):
	assignments = frappe.get_all(
		"Pledge",
		filters={"loan_security": ("in", securities), "parenttype": "Loan Security Assignment"},
		pluck="parent",
	)
	for assignment in frappe.get_all(
		"Loan Security Assignment",
		filters={"name": ("in", assignments), "loan": loan, "status": "Released", "docstatus": 1},
		pluck="name",
	):
		frappe.db.set_value(
			"Loan Security Assignment", assignment, {"status": "Pledged", "release_time": None}
		)


def validate_disbursement(doc):
	vehicles = get_loan_vehicles(doc.against_loan)
	if not vehicles:
		return

	for vehicle in frappe.get_all(
		"Loan Vehicle",
		filters={"name": ("in", vehicles), "asset_condition": "New"},
		fields=["name", "chassis_number", "engine_number"],
	):
		if not vehicle.chassis_number or not vehicle.engine_number:
			frappe.throw(
				_("Vehicle {0} needs a chassis and engine number before disbursement").format(
					frappe.bold(vehicle.name)
				)
			)

	blocking = frappe.get_all(
		"Post Disbursal Document",
		filters={
			"loan": doc.against_loan,
			"blocks_next_disbursement": 1,
			"status": ("in", ("Pending", "Overdue")),
			"due_date": ("<", getdate(doc.disbursement_date)),
		},
		fields=["name", "document_type", "vehicle"],
	)
	if blocking:
		documents = ", ".join(f"{d.document_type} ({d.vehicle})" for d in blocking)
		frappe.throw(
			_("Overdue post disbursal documents block this disbursement: {0}").format(documents),
			title=_("Pending PDD"),
		)


def create_post_disbursal_documents(doc):
	vehicles = get_loan_vehicles(doc.against_loan)
	if not vehicles:
		return

	loan_product = frappe.db.get_value("Loan", doc.against_loan, "loan_product")
	requirements = frappe.get_cached_doc("Loan Product", loan_product).get("pdd_requirements")
	if not requirements:
		return

	for vehicle in frappe.get_all(
		"Loan Vehicle",
		filters={"name": ("in", vehicles)},
		fields=["name", "asset_condition", "rc_copy", "invoice_copy"],
	):
		for requirement in requirements:
			if requirement.asset_condition and requirement.asset_condition != vehicle.asset_condition:
				continue

			if requirement.document_type == "RC" and vehicle.rc_copy:
				continue

			if requirement.document_type == "Tax Invoice" and vehicle.invoice_copy:
				continue

			if frappe.db.exists(
				"Post Disbursal Document",
				{"loan": doc.against_loan, "vehicle": vehicle.name, "document_type": requirement.document_type},
			):
				continue

			frappe.get_doc(
				{
					"doctype": "Post Disbursal Document",
					"loan": doc.against_loan,
					"loan_disbursement": doc.name,
					"vehicle": vehicle.name,
					"document_type": requirement.document_type,
					"due_date": add_days(doc.disbursement_date, requirement.due_in_days),
					"blocks_next_disbursement": requirement.blocks_next_disbursement,
				}
			).insert(ignore_permissions=True)


def delete_post_disbursal_documents(doc):
	remaining = frappe.get_all(
		"Loan Disbursement",
		filters={"against_loan": doc.against_loan, "docstatus": 1, "name": ("!=", doc.name)},
		order_by="disbursement_date asc, creation asc",
		pluck="name",
		limit=1,
	)

	for document in frappe.get_all(
		"Post Disbursal Document",
		filters={"loan_disbursement": doc.name},
		fields=["name", "status"],
	):
		if remaining:
			frappe.db.set_value("Post Disbursal Document", document.name, "loan_disbursement", remaining[0])
		elif document.status in OPEN_PDD_STATUSES:
			frappe.delete_doc("Post Disbursal Document", document.name, ignore_permissions=True)


@frappe.whitelist()
def issue_noc(loan: str):
	from lending.loan_management.doctype.loan_security_release.loan_security_release import (
		get_pledged_security_qty,
	)

	loan_doc = frappe.get_doc("Loan", loan)
	loan_doc.check_permission("write")

	allowed_statuses = ["Closed", "Loan Closure Requested"]
	if frappe.db.get_single_value("Lending Settings", "issue_noc_on_settled_loans"):
		allowed_statuses.append("Settled")

	if loan_doc.status not in allowed_statuses:
		frappe.throw(_("NOC cannot be issued for a loan in {0} status").format(frappe.bold(loan_doc.status)))

	vehicles = frappe.get_all(
		"Loan Vehicle",
		filters={"current_loan": loan, "status": ("in", ("Financed", "Released")), "noc_issued_on": ("is", "not set")},
		fields=["name", "loan_security"],
	)
	if not vehicles:
		frappe.throw(_("No vehicle on Loan {0} is waiting for a NOC").format(frappe.bold(loan)))

	pledged_qty = get_pledged_security_qty(loan=loan)
	securities = [
		{"loan_security": v.loan_security, "qty": pledged_qty[v.loan_security]}
		for v in vehicles
		if flt(pledged_qty.get(v.loan_security)) > 0
	]

	if securities:
		release = frappe.new_doc("Loan Security Release")
		release.applicant_type = loan_doc.applicant_type
		release.applicant = loan_doc.applicant
		release.loan = loan
		release.company = loan_doc.company
		release.description = _("Released on NOC issue")
		for security in securities:
			release.append("securities", security)
		release.insert()
		release.submit()
		release.status = "Approved"
		release.save()

	if not any(flt(qty) > 0 for qty in get_pledged_security_qty(loan=loan).values()):
		for assignment in frappe.get_all(
			"Loan Security Assignment",
			filters={"loan": loan, "status": "Pledged", "docstatus": 1},
			pluck="name",
		):
			frappe.db.set_value("Loan Security Assignment", assignment, "status", "Released")

	for vehicle in vehicles:
		frappe.db.set_value(
			"Loan Vehicle",
			vehicle.name,
			{"noc_issued_on": nowdate(), "noc_issued_by": frappe.session.user},
		)

	return [vehicle.name for vehicle in vehicles]
