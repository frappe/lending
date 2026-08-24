# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import frappe.permissions
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from lending.loan_origination.doctype.loan_lead.loan_lead import (
	CONTACT_IDENTITY_FIELDS,
	get_applicant_identity,
)

# Off as shipped, and only reached by the no-script path: the Server Script that runs the
# rule carries the limit a site actually sets.
DEFAULT_MAXIMUM_LIVE_LOANS = 0

# Committed, whether or not the money has gone out.
LIVE_LOAN_STATUSES = (
	"Sanctioned",
	"Partially Disbursed",
	"Disbursed",
	"Active",
	"Loan Closure Requested",
)

ADVERSE_LOAN_STATUSES = ("Written Off", "Settled")

# Employee loans are left out: an Employee is not matched by the fields a Customer carries.
LOAN_APPLICANT_TYPE = "Customer"

LOAN_DOCTYPE = "Loan"

CUSTOMER_FIELD_BY_LEAD_FIELD = {
	"pan": "pan",
	"email": "email_id",
	"mobile_number": "mobile_no",
}


def run_live_loan_limit_task(loan_lead: Document):
	validate_live_loan_limit(loan_lead, DEFAULT_MAXIMUM_LIVE_LOANS)


# Throws rather than rejecting the lead: Rejected would stamp rejected_on and start a
# cooling period over a rule the applicant did not fail.
#
# Whitelisted so a site's own Server Script can run the rule with its own limit;
# run_live_loan_limit_task is the no-script path.
@frappe.whitelist(methods=["POST"])
def validate_live_loan_limit(
	loan_lead: Document | str, maximum_live_loans: int | str | None = None
):
	if isinstance(loan_lead, str):
		loan_lead = frappe.get_doc("Loan Lead", loan_lead)

	# Write, not read: the rule gates taking the lead forward, so a caller who cannot act
	# on the lead has no business running it.
	loan_lead.check_permission("write")

	# And read on Loan on top of that. The count below comes out of the loan book without
	# permissions, so write on a lead is not enough on its own: a caller who can create a
	# lead could otherwise name any identity and probe whether it holds live loans. This
	# check keeps the answer to callers who could have looked the loans up anyway.
	check_loan_book_permission()

	# The caller's number is the only one there is: the limit lives in the Server Script
	# that runs this rule, so a site sets it in one place for every product.
	maximum_live_loans = cint(maximum_live_loans)
	if maximum_live_loans <= 0:
		return

	if get_live_loan_count(loan_lead) < maximum_live_loans:
		return

	frappe.throw(
		_(
			"This applicant already holds the maximum of {0} live loans, so this lead"
			" cannot be taken forward."
		).format(maximum_live_loans),
		title=_("Live Loan Limit"),
	)


def check_loan_book_permission():
	if not frappe.permissions.has_permission(LOAN_DOCTYPE, "read"):
		frappe.throw(_("Not permitted to read {0}").format(_(LOAN_DOCTYPE)), frappe.PermissionError)


def get_live_loan_count(loan_lead: Document | str) -> int:
	return get_applicant_exposure(loan_lead)["live_loan_count"]


# Deliberately not whitelisted: the return value is a full credit profile for whoever the
# lead's contact details match, and check_permission below is on the caller's own lead.
def get_applicant_exposure(loan_lead: Document | str) -> dict:
	if isinstance(loan_lead, str):
		loan_lead = frappe.get_doc("Loan Lead", loan_lead)

	# The loans are read without permissions, so this check fences that in.
	loan_lead.check_permission("read")

	customers = get_matching_customers(loan_lead)
	loans = get_live_and_adverse_loans(customers)

	live_loans = [loan for loan in loans if loan.status in LIVE_LOAN_STATUSES]

	return {
		"live_loan_count": len(live_loans),
		"total_sanctioned": sum(flt(loan.loan_amount) for loan in live_loans),
		"total_outstanding": sum(get_outstanding_principal(loan) for loan in live_loans),
		"max_days_past_due": max((loan.days_past_due or 0 for loan in live_loans), default=0),
		"npa_count": len([loan for loan in live_loans if loan.is_npa]),
		"adverse_loan_count": len([loan for loan in loans if loan.status in ADVERSE_LOAN_STATUSES]),
		"matched_customers": customers,
	}


def get_matching_customers(loan_lead: Document) -> list[str]:
	identity = get_customer_identity(loan_lead)
	if not identity:
		return []

	# Read without permissions; OR-matched, each identity field identifies the applicant.
	return frappe.db.get_all("Customer", or_filters=identity, pluck="name")


def get_customer_identity(loan_lead: Document) -> dict:
	identity = translate_identity_to_customer(get_applicant_identity(loan_lead))
	if identity:
		return identity

	# Nothing translated means PAN with no Customer field to hold it (an India Compliance
	# custom field), so fall back to contact details.
	return translate_identity_to_customer(
		{fieldname: loan_lead.get(fieldname) for fieldname in CONTACT_IDENTITY_FIELDS}
	)


def translate_identity_to_customer(identity: dict) -> dict:
	meta = frappe.get_meta("Customer")

	return {
		CUSTOMER_FIELD_BY_LEAD_FIELD[fieldname]: value
		for fieldname, value in identity.items()
		if value and meta.has_field(CUSTOMER_FIELD_BY_LEAD_FIELD[fieldname])
	}


def get_live_and_adverse_loans(customers: list[str]) -> list[frappe._dict]:
	if not customers:
		return []

	# Read without permissions; get_applicant_exposure is where that is fenced in.
	return frappe.db.get_all(
		"Loan",
		filters={
			"docstatus": 1,
			"applicant_type": LOAN_APPLICANT_TYPE,
			"applicant": ("in", customers),
			"status": ("in", LIVE_LOAN_STATUSES + ADVERSE_LOAN_STATUSES),
		},
		fields=[
			"name",
			"status",
			"company",
			"loan_product",
			"posting_date",
			"loan_amount",
			"total_payment",
			"total_interest_payable",
			"total_principal_paid",
			"days_past_due",
			"is_npa",
		],
	)


def get_outstanding_principal(loan: frappe._dict) -> float:
	outstanding = (
		flt(loan.total_payment) - flt(loan.total_interest_payable) - flt(loan.total_principal_paid)
	)

	# Floored per loan so an overpaid loan does not net off against one that is outstanding.
	return max(outstanding, 0.0)
