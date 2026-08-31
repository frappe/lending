# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import frappe.permissions
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from lending.loan_origination.doctype.loan_lead.loan_lead import (
	CONTACT_IDENTITY_FIELDS,
	get_applicant_identity,
	resolve_lead,
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


@frappe.whitelist(methods=["POST"])
def validate_live_loan_limit(
	loan_lead: Document | str, maximum_live_loans: int | str | None = None
):
	loan_lead = resolve_lead(loan_lead, "write")
	check_loan_book_permission()
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


# Deliberately not whitelisted: it answers a question about whoever the lead's contact
# details match, and resolve_lead below checks the caller's own lead.
def get_live_loan_count(loan_lead: Document | str) -> int:
	loan_lead = resolve_lead(loan_lead, "read")

	customers = get_matching_customers(loan_lead)
	if not customers:
		return 0

	# Counted without permissions; the check above is what fences that in.
	return frappe.db.count(
		LOAN_DOCTYPE,
		{
			"docstatus": 1,
			"applicant_type": LOAN_APPLICANT_TYPE,
			"applicant": ("in", customers),
			"status": ("in", LIVE_LOAN_STATUSES),
		},
	)


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
