# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from lending.portal.core import (
	APPLICATION_STAGES,
	STATUS_LABELS,
	assert_owns,
	clean,
	get_applications,
	get_loans,
	get_portal_customers,
	is_live,
	long_date,
	money,
	open_lead,
	shell_payload,
	tracker_stage,
)

DONE = ("done", "✓")
CURRENT = ("current", "●")
PENDING = ("pending", "○")

STATE_LABELS = {"done": "Done", "current": "In progress", "pending": "Waiting"}

DETAIL_FIELDS = (
	"name",
	"applicant",
	"applicant_name",
	"applicant_type",
	"status",
	"docstatus",
	"posting_date",
	"loan_product",
	"loan_amount",
	"maximum_loan_amount",
	"repayment_method",
	"repayment_periods",
	"rate_of_interest",
	"is_secured_loan",
	"loan_purpose",
	"total_payable_interest",
	"total_payable_amount",
	"address_line_1",
	"address_line_2",
	"city",
	"state",
	"zip_code",
	"country",
)


@frappe.whitelist()
def get_application_detail() -> dict:
	"""One application's tracker and details; the borrower's newest when none is named."""
	name = frappe.form_dict.get("name") or default_application()
	if not name:
		lead = open_lead()
		return lead_payload(lead) if lead else no_application_payload()

	assert_owns("Loan Application", name)
	application = frappe.db.get_value("Loan Application", name, DETAIL_FIELDS, as_dict=True)

	payload = shell_payload(_("Application"), _("Contact us"), borrower_loans())
	payload["head_note"] = "{0} · {1}".format(
		application.name, stage_label(application)
	)

	documents = document_rows(name)
	headline, headline_note = stage_headline(application, booked_loan(name))
	payload.update(
		{
			"has_application": True,
			"product": application.loan_product,
			"reference": _("Application {0}").format(application.name),
			"headline": headline,
			"headline_note": headline_note,
			"steps": get_application_steps(application),
			"steps_note": stage_note(application),
			"preview_note": _("As you sent it on {0}").format(long_date(application.posting_date)),
			"terms": term_rows(application),
			"terms_note": _("The loan you asked for"),
			"applicant": applicant_rows(application),
			"applicant_note": _("From your profile"),
			"co_applicants": co_applicant_rows(name),
			"co_applicants_note": co_applicants_note(name),
			"documents": documents,
			"documents_note": documents_note(documents),
		}
	)

	return payload


def default_application() -> str | None:
	customers = get_portal_customers()
	applications = get_applications(customers) if customers else []

	return applications[0]["name"] if applications else None


def borrower_loans() -> list[dict]:
	# All the borrower's loans, not this application's: the head badge speaks for every account.
	customers = get_portal_customers()

	return get_loans(customers) if customers else []


def no_application_payload() -> dict:
	payload = shell_payload(_("Application"), _("Apply for a loan"), borrower_loans())
	payload.update(
		{
			"has_application": False,
			"product": _("No application yet"),
			"reference": "",
			"headline": _("Apply for a loan and you can follow it here."),
			"headline_note": "",
			"steps": [],
			"steps_note": "",
			"preview_note": _("Nothing sent yet"),
			"terms": [],
			"terms_note": "",
			"applicant": [],
			"applicant_note": "",
			"co_applicants": [],
			"co_applicants_note": "",
			"documents": [],
			"documents_note": _("Nothing attached yet"),
		}
	)

	return payload


def lead_payload(lead: dict) -> dict:
	declined = lead.prequalification_status == "Not Pre-Qualified"

	payload = no_application_payload()
	payload["action_label"] = _("Contact us")
	payload["head_note"] = "{0} · {1}".format(lead.name, tracker_stage(lead))
	payload.update(
		{
			"has_application": True,
			"product": lead.loan_product,
			"reference": _("Enquiry {0}").format(lead.name),
			"headline": _("Not taken forward this time") if declined else _("We have your enquiry"),
			"headline_note": _("We cannot offer you a loan on these details. You may apply again later.")
			if declined
			else _("Our team will look at it and turn it into your application. You can follow it here."),
			"steps": get_lead_steps(lead),
			"steps_note": _("Closed") if declined else _("Waiting on us"),
			"preview_note": _("As you sent it on {0}").format(long_date(lead.creation)),
			"terms": [
				{"label": _("Product"), "value": lead.loan_product},
				{"label": _("Amount sought"), "value": money(lead.loan_amount)},
			],
			"terms_note": _("The loan you asked for"),
			"applicant": [{"label": _("Name"), "value": lead.applicant_name}],
			"applicant_note": _("From your enquiry"),
			"co_applicants_note": _("Just you"),
		}
	)

	return payload


def get_lead_steps(lead: dict) -> list[dict]:
	declined = lead.prequalification_status == "Not Pre-Qualified"
	qualified = lead.prequalification_status == "Pre-Qualified"

	steps = [
		step(
			_("Enquiry sent"),
			_("Sent {0}").format(long_date(lead.creation)),
			DONE,
			_("Enquiry"),
		),
		step(
			_("Checked against our rules"),
			_("Not taken forward")
			if declined
			else (_("Pre-qualified") if qualified else _("Our team is looking at your enquiry")),
			DONE if declined or qualified else CURRENT,
			_("Checks"),
		),
	]

	if not declined:
		steps += [
			step(
				_("Your application"),
				_("Our team is preparing it") if qualified else _("Starts once the checks are done"),
				CURRENT if qualified else PENDING,
				_("Application"),
			),
			step(_("Decision"), _("Awaited"), PENDING, _("Decision")),
		]

	return join_steps(steps)


def stage_label(application: dict) -> str:
	from lending.portal.core import application_stage

	stage, _tone = application_stage(
		application, application.docstatus == 0, booked_loan(application.name)
	)

	return stage


def stage_headline(application: dict, loan: dict) -> tuple[str, str]:
	# A refusal gives no reason: credit decisions stay off the portal.
	if application.docstatus == 0:
		return _("Your application is not sent yet"), _(
			"Finish the details and submit it, and we will start the review."
		)

	if loan and not is_live(loan):
		return _("Your loan is closed"), _("{0} is {1}. Its statement is still under Loans.").format(
			loan.name, STATUS_LABELS.get(loan.status, loan.status).lower()
		)

	if loan:
		return _("Your loan is open"), _("{0} is live. Your schedule and payments are under Loans.").format(
			loan.name
		)

	if application.status == "Approved":
		return _("Congratulations!"), _(
			"Your loan has been approved. We will get in touch with you about the disbursal."
		)

	if application.status == "Rejected":
		return _("Not approved this time"), _(
			"We could not approve this application. Contact us and we will talk it through."
		)

	return _("With our team"), _("We are assessing your application and will come back to you.")


def booked_loan(application: str) -> dict:
	return (
		frappe.db.get_value(
			"Loan",
			{"loan_application": application, "docstatus": 1},
			["name", "status"],
			as_dict=True,
		)
		or {}
	)


def step(title: str, detail: str, state: tuple, short: str = "") -> dict:
	code, marker = state

	return {
		"title": title,
		"detail": detail,
		"marker": marker,
		"state": _(STATE_LABELS[code]),
		"short": short or title,
		# Untranslated, so the page can compare it regardless of language.
		"code": code,
	}


def get_application_steps(application: dict) -> list[dict]:
	submitted = application.docstatus >= 1
	loan = booked_loan(application.name)
	# A booked loan counts as approved whatever status was left on the application.
	decided = bool(loan) or application.status in ("Approved", "Rejected")
	approved = bool(loan) or application.status == "Approved"

	steps = [
		step(
			_("Application started"),
			_("Initiated {0}").format(long_date(application.posting_date)),
			DONE,
			_("Started"),
		),
		step(
			_("Your details"),
			_("Submitted") if submitted else _("Finish and submit your application"),
			DONE if submitted else CURRENT,
			_("Details"),
		),
		step(
			_("Under review"),
			_("Our team is assessing your application")
			if submitted and not decided
			else (_("Assessed") if decided else _("Starts once you submit")),
			DONE if decided else (CURRENT if submitted else PENDING),
			_("Review"),
		),
		step(
			_("Decision"),
			_("Approved") if approved else (_("Not approved this time") if decided else _("Awaited")),
			DONE if decided else PENDING,
			_("Decision"),
		),
	]

	if loan:
		steps.append(
			step(
				_("Loan account"),
				"{0} · {1}".format(loan.name, STATUS_LABELS.get(loan.status, loan.status)),
				DONE,
				_("Loan"),
			)
		)

	return join_steps(steps)


def join_steps(steps: list[dict]) -> list[dict]:
	# A repeated block cannot tell it is the last copy, so the data marks the connector.
	for this, after in zip(steps, steps[1:]):
		this["line"] = "ok" if this["code"] == after["code"] == "done" else "plain"
	steps[-1]["line"] = ""

	return steps


def stage_note(application: dict) -> str:
	if application.docstatus == 0:
		return _("Waiting on you")

	if booked_loan(application.name):
		return _("Complete")

	if application.status == "Open":
		return _("Waiting on us")

	return APPLICATION_STAGES.get(application.status, application.status)


def term_rows(application: dict) -> list[dict]:
	rows = [
		(_("Product"), application.loan_product),
		(_("Amount sought"), money(application.loan_amount)),
		(_("Repayment"), application.repayment_method or _("Not chosen")),
		(_("Instalments"), str(application.repayment_periods or "")),
		(_("Interest rate"), "{0}% p.a.".format(flt(application.rate_of_interest, 2))),
		(_("Purpose"), application.loan_purpose or _("Not stated")),
		(_("Security"), _("Secured") if application.is_secured_loan else _("Unsecured")),
	]

	if flt(application.total_payable_amount):
		rows.append((_("Total payable"), money(application.total_payable_amount)))

	return [{"label": label, "value": value} for label, value in rows if value]


def applicant_rows(application: dict) -> list[dict]:
	rows = [
		(_("Name"), application.applicant_name or application.applicant),
		(_("Customer ID"), application.applicant),
		(_("Address"), format_address(application) or _("Not on record")),
	]

	return [{"label": label, "value": value} for label, value in rows]


def format_address(application: dict) -> str:
	parts = [
		application.address_line_1,
		application.address_line_2,
		application.city,
		application.state,
		str(application.zip_code) if application.zip_code else "",
		application.country,
	]

	return ", ".join(part for part in parts if part)


def co_applicant_rows(application: str) -> list[dict]:
	rows = frappe.get_all(
		"Loan Co-Applicants",
		filters={"parent": application, "parenttype": "Loan Application"},
		fields=["applicant_name", "applicant_email", "applicant_mobile"],
		ignore_permissions=True,
	)

	return [
		{
			"label": row.applicant_name or _("Unnamed"),
			"value": row.applicant_mobile or "",
			"detail": row.applicant_email or "",
		}
		for row in rows
	]


def co_applicants_note(application: str) -> str:
	count = frappe.db.count(
		"Loan Co-Applicants", {"parent": application, "parenttype": "Loan Application"}
	)

	return _("{0} on this application").format(count) if count else _("Just you")


def document_rows(application: str) -> list[dict]:
	# Attached only: no schema records which documents are still outstanding.
	rows = frappe.get_all(
		"Loan Application Document",
		filters={"parent": application, "parenttype": "Loan Application"},
		fields=["document_type", "file"],
		ignore_permissions=True,
	)

	return [
		{
			"label": row.document_type or _("Document"),
			"value": _("Uploaded"),
			"marker": "\u2713",
		}
		for row in rows
	]


def documents_note(documents: list[dict]) -> str:
	return (
		_("{0} attached").format(len(documents)) if documents else _("Nothing attached yet")
	)


ALLOWED_DOCUMENT_TYPES = (".pdf", ".png", ".jpg", ".jpeg")
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


@frappe.whitelist()
def get_document_choices() -> dict:
	customers = get_portal_customers()
	applications = get_applications(customers) if customers else []

	# Only drafts take new documents.
	open_applications = [
		{"label": f"{row['name']} · {row['product']}", "value": row["name"]}
		for row in applications
		if row.get("needs_borrower")
	]

	return {
		"application_options": open_applications,
		"document_type_options": [
			{"label": row, "value": row}
			for row in frappe.get_all("Loan Document Type", pluck="name", order_by="name asc")
		],
		"can_upload": bool(open_applications),
		"upload_label": _("Send this document"),
	}


def editable_application() -> str:
	name = clean(frappe.form_dict.get("application"))
	if not name:
		raise frappe.PermissionError(_("Not permitted"))

	assert_owns("Loan Application", name)

	if frappe.db.get_value("Loan Application", name, "docstatus") != 0:
		frappe.throw(
			_("This application is with our team now, so it cannot take new documents."),
			frappe.ValidationError,
		)

	return name


def read_upload():
	upload = (frappe.request.files or {}).get("file") if frappe.request else None
	if not upload:
		frappe.throw(_("Please choose a file."), frappe.ValidationError)

	content = upload.stream.read()
	if not content:
		frappe.throw(_("That file is empty."), frappe.ValidationError)

	if len(content) > MAX_DOCUMENT_BYTES:
		frappe.throw(
			_("Please keep the file under {0} MB.").format(MAX_DOCUMENT_BYTES // (1024 * 1024)),
			frappe.ValidationError,
		)

	filename = clean(upload.filename)
	if not filename.lower().endswith(ALLOWED_DOCUMENT_TYPES):
		frappe.throw(
			_("Please send a PDF or a photo ({0}).").format(", ".join(ALLOWED_DOCUMENT_TYPES)),
			frappe.ValidationError,
		)

	return filename, content


@frappe.whitelist(methods=["POST"])
def upload_document() -> dict:
	"""Attach a private file to one of the borrower's own draft applications."""
	# ignore_permissions below: Website Users hold no write on Loan Application; ownership is checked here.
	application = editable_application()
	document_type = clean(frappe.form_dict.get("document_type"))

	if not frappe.db.exists("Loan Document Type", document_type):
		frappe.throw(_("Please choose a document type from the list."), frappe.ValidationError)

	filename, content = read_upload()

	stored = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "Loan Application",
			"attached_to_name": application,
		}
	).insert(ignore_permissions=True)

	document = frappe.get_doc("Loan Application", application)
	document.append("documents", {"document_type": document_type, "file": stored.file_url})
	document.save(ignore_permissions=True)

	return {
		"headline": _("Uploaded"),
		"message": _("{0} has been added to {1}.").format(document_type, application),
		"offer": [],
		"reference_note": "",
	}
