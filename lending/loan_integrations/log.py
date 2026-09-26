# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe

# A signed link carries its own credential in its query string, hence url and link.
SENSITIVE = re.compile(
	r"secret|password|otp|aadhaar|token|pin|cvv|url|link|pan|mobile|phone|email|dob|\bname\b",
	re.IGNORECASE,
)

SENSITIVE_VALUE = re.compile(r"\bhttps?://", re.IGNORECASE)

REDACTED = "***"

# Failed is the one status run_integration will call over again, so it carries a narrow meaning:
# the provider never answered, and nothing is spent by asking a second time. Once it has answered
# the enquiry is permanent, so a lost answer is parked under this status for a person to settle.
FAILED = "Failed"
UNRECORDED = "Authorized"


def start(service, operation, context, reference_doctype, reference_docname, url):
	request = frappe.get_doc(
		{
			"doctype": "Integration Request",
			"integration_request_service": service,
			"request_description": operation,
			"status": "Queued",
			"is_remote_request": 1,
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"url": url,
			"data": frappe.as_json(redact(context), indent=1),
		}
	)
	request.insert(ignore_permissions=True)

	return request


def find_existing(service, operation, reference_doctype, reference_docname):
	return frappe.db.get_value(
		"Integration Request",
		{
			"integration_request_service": service,
			"request_description": operation,
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
		},
		["name", "status", "output"],
		order_by="creation desc",
		as_dict=True,
	)


def stored_output(existing) -> dict:
	return frappe.parse_json(existing.output) or {}


def succeed(request, parsed, extra=None):
	output = {**parsed, **(extra or {})}

	if external_id := parsed.get("external_id"):
		request.db_set("request_id", external_id, update_modified=False)

	request.db_set(
		{"status": "Completed", "output": frappe.as_json(redact(output), indent=1)},
		update_modified=False,
	)

	return output


def fail(request, exc):
	"""The provider never answered, so nothing was spent and the call may be made again."""
	record_error(request, FAILED, exc)


def leave_unrecorded(request, exc, parsed=None):
	"""The provider answered, so the enquiry is spent even though we could not store what it said.

	Deliberately not Failed: asking again bills us a second time and leaves a second permanent
	enquiry on the applicant's file. Someone reads the row and decides. The provider's own
	reference is kept where it is known, since that is the only thread back to what we paid for.
	"""
	record_error(request, UNRECORDED, exc, (parsed or {}).get("external_id"))


def record_error(request, status, exc, external_id=None):
	values = {"status": status, "error": f"{type(exc).__name__}: {exc}"}

	if external_id:
		values["request_id"] = external_id

	request.db_set(values, update_modified=False)

	# Never with_context: it renders frame locals, leaking past everything redact() removed.
	frappe.log_error(
		title=f"Integration failed: {request.integration_request_service} {request.request_description}",
		message=frappe.get_traceback(),
		reference_doctype="Integration Request",
		reference_name=request.name,
	)


def redact(value):
	if isinstance(value, dict):
		return {k: REDACTED if SENSITIVE.search(str(k)) else redact(v) for k, v in value.items()}

	if isinstance(value, list | tuple):
		return [redact(v) for v in value]

	if isinstance(value, str) and SENSITIVE_VALUE.search(value):
		return REDACTED

	return value
