# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.query_builder import functions as fn
from frappe.utils import flt, get_datetime

from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)


class LoanSecurityShortfall(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		applicant: DF.DynamicLink | None
		applicant_email: DF.Data | None
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		cure_by: DF.Date | None
		cure_method: DF.Literal["", "Repayment", "Additional Pledge", "Price Recovery", "Sale"]
		email_missing: DF.Check
		loan: DF.Link | None
		loan_amount: DF.Currency
		missing_price: DF.Check
		notified_on: DF.Datetime | None
		process_loan_security_shortfall: DF.Link | None
		security_value: DF.Currency
		shortfall_amount: DF.Currency
		shortfall_percentage: DF.Percent
		shortfall_time: DF.Datetime | None
		status: DF.Literal["", "Pending", "Notified", "Escalated", "Sale Triggered", "Completed"]
	# end: auto-generated types

	pass


OPEN_STATUSES = ("Pending", "Notified", "Escalated", "Sale Triggered")
DRAWN_SECURED_LOANS = {"status": ("in", ["Disbursed", "Partially Disbursed"]), "is_secured_loan": 1}
OUTSTANDING_FIELDS = [
	"name",
	"loan_amount",
	"total_principal_paid",
	"total_payment",
	"total_interest_payable",
	"disbursed_amount",
	"status",
]


class CollateralValuation:
	"""Values a loan's pledged collateral at current prices against each security's LTV and sell level."""

	def __init__(self, price_map=None):
		self.price_map = price_map if price_map is not None else get_current_price_map()
		self.ltv_ratio_map = get_ltv_ratio_map()
		self.sell_ltv_map = get_ltv_ratio_map(field="sell_ltv")

	def value_loan(self, loan):
		collateral = frappe._dict(
			pledged_qty=get_pledged_security_qty(loan=loan),
			security_value=0.0,
			allowed_amount=0.0,
			sell_amount=0.0,
			has_sell_level=False,
			missing_price=False,
		)
		for security, qty in collateral.pledged_qty.items():
			# Fully released or sold securities stay in the map at 0 and must not bring their sell level
			if flt(qty) <= 0:
				continue
			collateral.missing_price = collateral.missing_price or not flt(self.price_map.get(security))
			value = flt(self.price_map.get(security)) * flt(qty)
			sell_ltv = flt(self.sell_ltv_map.get(security))
			collateral.security_value += value
			collateral.allowed_amount += value * flt(self.ltv_ratio_map.get(security)) / 100
			# A security with no sell level never triggers an early sale by itself
			collateral.sell_amount += value * (sell_ltv or 100) / 100
			collateral.has_sell_level = collateral.has_sell_level or bool(sell_ltv)
		return collateral


def get_current_price_map():
	update_time = get_datetime()
	return frappe._dict(
		frappe.get_all(
			"Loan Security Price",
			fields=["loan_security", "loan_security_price"],
			filters={"valid_from": ("<=", update_time), "valid_upto": (">=", update_time)},
			as_list=1,
		)
	)


def get_outstanding_amount(loan):
	drawn_amount = loan.total_payment if loan.status == "Disbursed" else loan.disbursed_amount
	return flt(drawn_amount) - flt(loan.total_interest_payable) - flt(loan.total_principal_paid)


def get_current_ltv(loan_amount, security_value):
	return (flt(loan_amount) / security_value) * 100 if security_value else 0


def update_shortfall_status(loan, security_value, on_cancel=0, cure_method=None):
	loan_security_shortfall = frappe.db.get_value(
		"Loan Security Shortfall",
		{"loan": loan, "status": ("in", OPEN_STATUSES)},
		["name", "shortfall_amount", "creation"],
		as_dict=1,
		for_update=True,
	)

	if not loan_security_shortfall:
		return

	if security_value >= loan_security_shortfall.shortfall_amount:
		frappe.db.set_value(
			"Loan Security Shortfall",
			loan_security_shortfall.name,
			{
				"status": "Completed",
				"shortfall_amount": loan_security_shortfall.shortfall_amount,
				"shortfall_percentage": 0,
				"cure_method": cure_method or get_cure_method(loan_security_shortfall, loan),
			},
		)
		discard_untouched_sales(loan_security_shortfall.name)
	else:
		frappe.db.set_value(
			"Loan Security Shortfall",
			loan_security_shortfall.name,
			"shortfall_amount",
			loan_security_shortfall.shortfall_amount - security_value,
		)


@frappe.whitelist()
def add_security(loan: str):
	frappe.has_permission("Loan", "read", doc=loan, throw=True)

	loan_details = frappe.db.get_value(
		"Loan", loan, ["applicant", "company", "applicant_type"], as_dict=1
	)

	loan_security_assignment = frappe.new_doc("Loan Security Assignment")
	loan_security_assignment.loan = loan
	loan_security_assignment.company = loan_details.company
	loan_security_assignment.applicant_type = loan_details.applicant_type
	loan_security_assignment.applicant = loan_details.applicant
	loan_security_assignment.security_owner_type = loan_details.applicant_type
	loan_security_assignment.security_owner = loan_details.applicant

	return loan_security_assignment.as_dict()


def check_for_ltv_shortfall(process_loan_security_shortfall, loan=None, applicant=None):
	from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
		get_total_pledged_security_value,
	)

	loan_security_price_map = get_current_price_map()

	filters = dict(DRAWN_SECURED_LOANS)

	if loan:
		filters["name"] = loan

	if applicant:
		filters["applicant"] = applicant

	loans = frappe.get_all("Loan", fields=OUTSTANDING_FIELDS, filters=filters)

	applicant_filters = {}
	if applicant:
		applicant_filters["name"] = applicant

	applicants= frappe.db.get_all("Customer", filters=applicant_filters, pluck="name")

	loan_shortfall_map = frappe._dict(
		frappe.get_all(
			"Loan Security Shortfall",
			fields=["loan", "name"],
			filters={"status": ("in", OPEN_STATUSES)},
			as_list=1,
		)
	)

	valuation = CollateralValuation(loan_security_price_map)

	# Loan-wise shortfall processing
	for loan in loans:
		outstanding_amount = get_outstanding_amount(loan)
		collateral = valuation.value_loan(loan.name)

		shortfall_amount = outstanding_amount - collateral.allowed_amount
		# A security with no current price is valued at 0, so a missing price raises a shortfall
		if has_pledged_qty(collateral.pledged_qty) and flt(shortfall_amount, 6) > 0:
			create_loan_security_shortfall(
				outstanding_amount,
				collateral.security_value,
				shortfall_amount,
				get_current_ltv(outstanding_amount, collateral.security_value),
				process_loan_security_shortfall,
				loan=loan.name,
				# A missing price counts as 0 and would start a sale on data, not on a price fall
				sale_triggered=not collateral.missing_price
				and collateral.has_sell_level
				and flt(outstanding_amount - collateral.sell_amount, 6) > 0,
				missing_price=collateral.missing_price,
			)
		elif loan_shortfall_map.get(loan.name) and flt(shortfall_amount, 6) <= 0:
			update_pending_shortfall(loan_shortfall_map.get(loan.name), loan.name)

	# Applicant-wise shortfall processing
	for applicant in applicants:
		security_value = get_total_pledged_security_value(applicant=applicant, on_shortfall_check=True)
		pending_principal_amount = get_pending_principal_amount_for_applicant(applicant)

		shortfall_amount = security_value - pending_principal_amount
		if flt(shortfall_amount) < 0:
			collateral = get_applicant_collateral(applicant, loan_security_price_map)
			create_loan_security_shortfall(
				pending_principal_amount,
				security_value,
				abs(shortfall_amount),
				get_current_ltv(pending_principal_amount, collateral.security_value),
				process_loan_security_shortfall,
				applicant=applicant,
				missing_price=collateral.missing_price,
			)

		sanctioned_limit = frappe.db.get_value(
			"Sanctioned Loan Amount", {"applicant": applicant}, "name"
		)
		if sanctioned_limit:
			frappe.db.set_value(
				"Sanctioned Loan Amount", sanctioned_limit, "sanctioned_amount_limit", security_value
			)


def create_loan_security_shortfall(
	loan_amount,
	security_value,
	shortfall_amount,
	shortfall_ratio,
	process_loan_security_shortfall,
	loan=None,
	applicant=None,
	sale_triggered=False,
	missing_price=False,
):

	if loan:
		filters = {"loan": loan, "status": ("in", OPEN_STATUSES)}
	elif applicant:
		# Exclude loan-linked shortfalls: the applicant field is auto-filled via
		# fetch_from="loan.applicant", so without this guard the applicant-wise path
		# would find and overwrite loan-wise shortfalls with wrong security_value.
		filters = {"applicant": applicant, "status": ("in", OPEN_STATUSES), "loan": ("is", "not set")}

	existing_shortfall = frappe.db.get_value(
		"Loan Security Shortfall", filters=filters, fieldname="name"
	)

	if existing_shortfall:
		ltv_shortfall = frappe.get_doc("Loan Security Shortfall", existing_shortfall)
	else:
		ltv_shortfall = frappe.new_doc("Loan Security Shortfall")
		ltv_shortfall.loan = loan

	ltv_shortfall.applicant_type = "Customer"
	ltv_shortfall.applicant = applicant
	ltv_shortfall.shortfall_time = get_datetime()
	ltv_shortfall.loan_amount = loan_amount
	ltv_shortfall.security_value = security_value
	ltv_shortfall.shortfall_amount = shortfall_amount
	ltv_shortfall.shortfall_percentage = shortfall_ratio
	ltv_shortfall.process_loan_security_shortfall = process_loan_security_shortfall
	ltv_shortfall.missing_price = missing_price
	if sale_triggered:
		ltv_shortfall.status = "Sale Triggered"
	ltv_shortfall.save()


def get_ltv_ratio_map(loan_securities=None, field="loan_to_value_ratio"):
	"""LTV of each Loan Security, or of its Loan Security Type when the security has none.

	`field` can be sell_ltv to read the sell level the same way."""
	security = frappe.qb.DocType("Loan Security")
	security_type = frappe.qb.DocType("Loan Security Type")

	query = (
		frappe.qb.from_(security)
		.left_join(security_type)
		.on(security.loan_security_type == security_type.name)
		.select(
			security.name,
			security[field].as_("security_ratio"),
			security_type[field].as_("type_ratio"),
		)
	)
	if loan_securities:
		query = query.where(security.name.isin(loan_securities))

	return {
		row.name: flt(row.security_ratio) or flt(row.type_ratio)
		for row in query.run(as_dict=True)
	}


def has_pledged_qty(pledged_securities):
	return any(flt(qty) > 0 for qty in pledged_securities.values())


def get_applicant_collateral(applicant, loan_security_price_map):
	held = {
		security: flt(qty)
		for security, qty in get_pledged_security_qty(applicant=applicant).items()
		if flt(qty) > 0
	}
	return frappe._dict(
		security_value=sum(flt(loan_security_price_map.get(security)) * qty for security, qty in held.items()),
		missing_price=any(not flt(loan_security_price_map.get(security)) for security in held),
	)


def recheck_loan_shortfall(loan, cure_method=None):
	"""Re-value the loan of an open shortfall after its collateral changed, at each security's LTV."""
	shortfall = frappe.db.get_value(
		"Loan Security Shortfall",
		{"loan": loan, "status": ("in", OPEN_STATUSES)},
		"name",
		for_update=True,
	)
	if not shortfall:
		return

	outstanding_amount = get_outstanding_amount(
		frappe.db.get_value("Loan", loan, OUTSTANDING_FIELDS, as_dict=1)
	)
	collateral = CollateralValuation().value_loan(loan)
	shortfall_amount = outstanding_amount - collateral.allowed_amount

	if flt(shortfall_amount, 6) <= 0:
		update_pending_shortfall(shortfall, loan, cure_method)
	else:
		frappe.db.set_value(
			"Loan Security Shortfall",
			shortfall,
			{
				"security_value": collateral.security_value,
				"shortfall_amount": shortfall_amount,
				"shortfall_percentage": get_current_ltv(outstanding_amount, collateral.security_value),
			},
		)


def update_pending_shortfall(shortfall, loan, cure_method=None):
	shortfall_details = frappe.db.get_value(
		"Loan Security Shortfall", shortfall, ["name", "creation"], as_dict=1
	)
	frappe.db.set_value(
		"Loan Security Shortfall",
		shortfall,
		{
			"status": "Completed",
			"shortfall_amount": 0,
			"shortfall_percentage": 0,
			"cure_method": cure_method or get_cure_method(shortfall_details, loan),
		},
	)
	discard_untouched_sales(shortfall)


def discard_untouched_sales(shortfall):
	"""Delete draft sales of a cured shortfall that staff have not started filling in."""
	for sale in frappe.get_all(
		"Loan Security Sale", filters={"loan_security_shortfall": shortfall, "docstatus": 0}, pluck="name"
	):
		if not frappe.db.exists("Loan Security Sale Item", {"parent": sale, "sold_qty": (">", 0)}):
			frappe.delete_doc("Loan Security Sale", sale, ignore_permissions=True)


def get_cure_method(shortfall, loan):
	"""Best guess at what cured the shortfall, from what happened to the loan since it opened."""
	if frappe.db.exists("Loan Security Sale", {"loan_security_shortfall": shortfall.name, "docstatus": 1}):
		return "Sale"

	since = {"creation": (">=", shortfall.creation), "docstatus": 1}
	if frappe.db.exists("Loan Repayment", {"against_loan": loan, **since}):
		return "Repayment"
	if frappe.db.exists("Loan Security Assignment", {"loan": loan, "status": "Pledged", **since}):
		return "Additional Pledge"
	return "Price Recovery"


def get_pending_principal_amount_for_applicant(applicant):
	loan = frappe.qb.DocType("Loan")
	pending_principal_amount = frappe.qb.from_(loan).select(
		fn.Sum(loan.total_payment) - fn.Sum(loan.total_interest_payable) - fn.Sum(loan.total_principal_paid)
	).where(
		(loan.applicant == applicant) & (loan.status.isin(["Disbursed", "Partially Disbursed"]))
	).run()

	return flt(pending_principal_amount[0][0])
