# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.workflow import get_workflow_name, get_workflow_state_field
from frappe.rate_limiter import rate_limit
from frappe.utils import add_days, cint, getdate, now_datetime

TELEPHONY_APP = "telephony"
REJECTED_WORKFLOW_STATE = "Rejected"
PAN_COUNTRY = "India"
PAN_IDENTITY_FIELDS = ("pan",)
CONTACT_IDENTITY_FIELDS = ("email", "mobile_number")
DEFAULT_COOLING_PERIOD_DAYS = 30

MAX_BULK_OTP_LEADS = 50
OTP_SEND_LIMIT = 30
OTP_VERIFY_LIMIT = 60
BULK_OTP_SEND_LIMIT = 5
OTP_RATE_LIMIT_WINDOW = 60 * 60

OTP_MEDIUM_FIELD_MAP = {
	"Email": {
		"recipient_field": "email",
		"status_field": "email_verification_status",
		"enable_field": "otp_for_email",
		"telephony_field": "enable_email_otp",
		"telephony_label": "Email OTP",
	},
	"SMS": {
		"recipient_field": "mobile_number",
		"status_field": "mobile_verification_status",
		"enable_field": "otp_for_sms",
		"telephony_field": "enabled",
		"telephony_label": "SMS",
	},
}


class LoanLead(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		address: DF.Link | None
		age: DF.Int
		amended_from: DF.Link | None
		applicant_country: DF.Link | None
		applicant_name: DF.Data
		applicant_type: DF.Literal["Individual", "Business"]
		company_name: DF.Data | None
		contact: DF.Link | None
		date_of_birth: DF.Date | None
		email: DF.Data
		email_verification_status: DF.Literal["Pending", "Initiated", "Verified"]
		employment_type: DF.Literal["Salaried", "Self-employed"]
		income: DF.Currency
		indicative_amount: DF.Currency
		indicative_roi: DF.Percent
		indicative_tenure: DF.Int
		lead_source: DF.Data | None
		loan_amount: DF.Currency
		loan_product: DF.Link
		mobile_number: DF.Phone
		mobile_verification_status: DF.Literal["Pending", "Initiated", "Verified"]
		pan: DF.Data | None
		prequalification_reason_codes: DF.SmallText | None
		prequalification_status: DF.Literal["", "Pre-Qualified", "Not Pre-Qualified", "Referred"]
		prequalified_on: DF.Datetime | None
		proposed_tenure: DF.Int
		rejected_on: DF.Datetime | None
		status: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self.set_age()
		self.set_verification_statuses()
		self.set_rejected_on()

	def set_age(self):
		if self.applicant_type != "Individual":
			self.age = 0
			return

		today, date_of_birth = getdate(), getdate(self.date_of_birth)
		self.age = (
			today.year
			- date_of_birth.year
			- ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
		)

	def set_rejected_on(self):
		workflow = get_workflow_name(self.doctype)
		if not workflow:
			return

		state_field = get_workflow_state_field(workflow)
		if not state_field:
			return

		if self.get(state_field) == REJECTED_WORKFLOW_STATE:
			if not self.rejected_on:
				self.rejected_on = now_datetime()
		else:
			self.rejected_on = None

	def set_verification_statuses(self):
		before_save = self.get_doc_before_save()

		for fields in OTP_MEDIUM_FIELD_MAP.values():
			stored_status = before_save.get(fields["status_field"]) if before_save else None

			if stored_status and not self.has_value_changed(fields["recipient_field"]):
				self.set(fields["status_field"], stored_status)
			else:
				self.set(fields["status_field"], "Pending")


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=OTP_SEND_LIMIT, seconds=OTP_RATE_LIMIT_WINDOW, methods=["POST"])
def send_otp(loan_lead: str, medium: str):
	return send_otp_for_lead(loan_lead, medium)


def send_otp_for_lead(loan_lead: str, medium: str):
	doc, fields, recipient = resolve_otp_request(loan_lead, medium)

	if doc.get(fields["status_field"]) == "Verified":
		frappe.throw(_("{0} is already verified for this lead.").format(medium))

	result = get_telephony_otp().send_otp(recipient, medium, purpose=get_otp_purpose(loan_lead))
	mark_otp_status(doc, fields, recipient, "Initiated")

	return result


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=OTP_VERIFY_LIMIT, seconds=OTP_RATE_LIMIT_WINDOW, methods=["POST"])
def verify_otp(loan_lead: str, medium: str, otp: str):
	doc, fields, recipient = resolve_otp_request(loan_lead, medium)

	result = get_telephony_otp().verify_otp(
		recipient, medium, otp, purpose=get_otp_purpose(loan_lead)
	)

	if result.get("verified"):
		mark_otp_status(doc, fields, recipient, "Verified")

	return result


def mark_otp_status(doc: Document, fields: dict, recipient: str, status: str):
	frappe.db.set_value(
		"Loan Lead",
		{"name": doc.name, fields["recipient_field"]: recipient},
		fields["status_field"],
		status,
	)
	marked = frappe.db.get_value(
		"Loan Lead",
		{
			"name": doc.name,
			fields["recipient_field"]: recipient,
			fields["status_field"]: status,
		},
		"name",
	)

	if not marked:
		frappe.throw(
			_("{0} changed while the OTP was in flight. Please try again.").format(
				_(doc.meta.get_label(fields["recipient_field"]))
			)
		)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=BULK_OTP_SEND_LIMIT, seconds=OTP_RATE_LIMIT_WINDOW, methods=["POST"])
def bulk_send_otp(loan_leads: list[str] | str, medium: str):
	if isinstance(loan_leads, str):
		loan_leads = frappe.parse_json(loan_leads)

	if not isinstance(loan_leads, (list, tuple)) or not all(
		isinstance(loan_lead, str) for loan_lead in loan_leads
	):
		frappe.throw(_("Please pass Loan Leads as a list of lead names."))

	if len(loan_leads) > MAX_BULK_OTP_LEADS:
		frappe.throw(
			_("Cannot send an OTP to more than {0} leads at a time.").format(MAX_BULK_OTP_LEADS)
		)

	loan_leads = list(dict.fromkeys(loan_leads))

	sent, failed = [], []
	for loan_lead in loan_leads:
		save_point = f"otp_{frappe.generate_hash(length=10)}"
		frappe.db.savepoint(save_point)

		try:
			send_otp_for_lead(loan_lead, medium)
		except Exception as e:
			frappe.db.rollback(save_point=save_point)
			frappe.clear_last_message()
			failed.append({"loan_lead": loan_lead, "error": str(e) or _("Could not send the OTP.")})
		else:
			frappe.db.release_savepoint(save_point)
			sent.append(loan_lead)

	return {"sent": sent, "failed": failed}


@frappe.whitelist()
def get_enabled_otp_mediums() -> list[str]:
	frappe.has_permission("Loan Lead", throw=True)

	settings = frappe.get_cached_doc("Loan Origination Settings")

	return [
		medium
		for medium, fields in OTP_MEDIUM_FIELD_MAP.items()
		if settings.get(fields["enable_field"])
	]


def resolve_otp_request(loan_lead: str, medium: str) -> tuple[Document, dict, str]:
	if medium not in OTP_MEDIUM_FIELD_MAP:
		frappe.throw(_("Medium must be one of: {0}.").format(", ".join(OTP_MEDIUM_FIELD_MAP)))

	fields = OTP_MEDIUM_FIELD_MAP[medium]

	try:
		doc = frappe.get_doc("Loan Lead", loan_lead)
		permitted = doc.has_permission("write")
	except frappe.DoesNotExistError:
		frappe.clear_last_message()
		permitted = False

	if not permitted:
		frappe.throw(
			_("You do not have permission to send an OTP for {0}.").format(loan_lead),
			frappe.PermissionError,
		)

	if not doc.docstatus.is_draft():
		frappe.throw(_("An OTP can only be sent while the lead is a draft."))

	settings = frappe.get_cached_doc("Loan Origination Settings")
	if not settings.get(fields["enable_field"]):
		frappe.throw(_("OTP for {0} is not enabled in Loan Origination Settings.").format(medium))

	recipient = doc.get(fields["recipient_field"])
	if not recipient:
		frappe.throw(
			_("Please set {0} on this lead first.").format(
				_(doc.meta.get_label(fields["recipient_field"]))
			)
		)

	return doc, fields, recipient


def get_otp_purpose(loan_lead: str) -> str:
	return f"Loan Lead {loan_lead}"


def get_telephony_otp():
	if TELEPHONY_APP not in frappe.get_installed_apps():
		frappe.throw(_("Please install the Telephony app to send and verify OTPs."))

	from telephony import otp

	return otp


def validate_otp_verification(loan_lead: Document):
	settings = frappe.get_cached_doc("Loan Origination Settings")
	if not settings.otp_verification_mandatory:
		return

	statuses = frappe.db.get_value(
		"Loan Lead",
		loan_lead.name,
		[fields["status_field"] for fields in OTP_MEDIUM_FIELD_MAP.values()],
		as_dict=True,
	)

	unverified = [
		fields["recipient_field"]
		for fields in OTP_MEDIUM_FIELD_MAP.values()
		if settings.get(fields["enable_field"])
		and statuses.get(fields["status_field"]) != "Verified"
	]

	if unverified:
		meta = frappe.get_meta("Loan Lead")
		frappe.throw(
			_("Please verify the applicant's {0} before converting this lead.").format(
				", ".join(_(meta.get_label(fieldname)) for fieldname in unverified)
			)
		)


def resolve_lead(loan_lead: Document | str, ptype: str) -> Document:
	if isinstance(loan_lead, str):
		loan_lead = frappe.get_doc("Loan Lead", loan_lead)

	loan_lead.check_permission(ptype)

	return loan_lead


def assert_called_from_a_rule():
	if frappe.request and not frappe.flags.in_safe_exec:
		frappe.throw(
			_("This rule runs as a workflow task and cannot be called directly."),
			frappe.PermissionError,
		)


def run_cooling_period_task(loan_lead: Document):
	validate_cooling_period(loan_lead, DEFAULT_COOLING_PERIOD_DAYS)


@frappe.whitelist(methods=["POST"])
def validate_cooling_period(
	loan_lead: Document | str, cooling_period_days: int | str | None = None
):
	assert_called_from_a_rule()

	loan_lead = resolve_lead(loan_lead, "write")

	cooling_period_days = cint(get_product_cooling_period(loan_lead) or cooling_period_days)
	if cooling_period_days <= 0:
		return

	rejection = get_last_rejection(loan_lead, cooling_period_days)
	if not rejection:
		return

	frappe.throw(
		_(
			"This applicant was rejected within the last {0} days. A cooling period"
			" applies, so this lead cannot be taken forward yet."
		).format(cooling_period_days),
		title=_("Cooling Period"),
	)


def get_product_cooling_period(loan_lead: Document) -> int:
	if not loan_lead.get("loan_product"):
		return 0

	return cint(
		frappe.get_value("Loan Product", loan_lead.loan_product, "cooling_period_days", cache=True)
	)


def get_contact_identity(loan_lead: Document) -> dict:
	return {
		fieldname: loan_lead.get(fieldname)
		for fieldname in CONTACT_IDENTITY_FIELDS
		if loan_lead.get(fieldname)
	}


def get_applicant_identity(loan_lead: Document) -> dict:
	# A PAN identifies the applicant on its own, whether or not the country was ever set.
	if not loan_lead.get("pan"):
		return get_contact_identity(loan_lead)

	return {
		fieldname: loan_lead.get(fieldname)
		for fieldname in PAN_IDENTITY_FIELDS
		if loan_lead.get(fieldname)
	}


def get_last_rejection(loan_lead: Document, cooling_period_days: int) -> frappe._dict | None:
	identity = get_applicant_identity(loan_lead)
	if not identity:
		return None

	filters = {
		"rejected_on": (">", add_days(now_datetime(), -cooling_period_days)),
		"docstatus": ("!=", 2),
	}

	if loan_lead.name:
		filters["name"] = ("!=", loan_lead.name)

	rejections = frappe.db.get_all(
		"Loan Lead",
		filters=filters,
		or_filters=identity,
		fields=["name", "rejected_on"],
		order_by="rejected_on desc",
		limit=1,
	)

	return rejections[0] if rejections else None


# A workflow task, called as method(doc). Not whitelisted: over HTTP loan_lead would
# arrive as a name rather than the document this reads fields off.
def convert_to_loan_application(loan_lead: Document):
	loan_lead.check_permission("read")
	frappe.has_permission("Loan Application", "create", throw=True)
	validate_otp_verification(loan_lead)

	loan_application = frappe.new_doc("Loan Application")
	loan_application.loan_lead = loan_lead.name
	loan_application.applicant_email_address = loan_lead.email
	loan_application.applicant_name = loan_lead.applicant_name
	loan_application.applicant_phone_number = loan_lead.mobile_number
	loan_application.loan_product = loan_lead.loan_product
	loan_application.loan_amount = loan_lead.loan_amount
	loan_application.repayment_periods = loan_lead.proposed_tenure

	loan_application.save()
