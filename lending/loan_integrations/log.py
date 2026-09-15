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


def start(provider, operation, context, reference_doctype, reference_docname, url):
	request = frappe.get_doc(
		{
			"doctype": "Integration Request",
			"integration_request_service": provider,
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


def find_existing(provider, operation, reference_doctype, reference_docname):
	return frappe.db.get_value(
		"Integration Request",
		{
			"integration_request_service": provider,
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
	request.db_set(
		{"status": "Failed", "error": f"{type(exc).__name__}: {exc}"}, update_modified=False
	)

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
