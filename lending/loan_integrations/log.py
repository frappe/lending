# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe

# url and link look harmless and are not: a signed link carries the credential that signs it,
# with the key and signature in the query string. We fetch what it points at during the call.
SENSITIVE = re.compile(r"secret|password|otp|aadhaar|token|pin|cvv|url|link", re.IGNORECASE)
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
			"status": ["!=", "Failed"],
		},
		"name",
	)


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

	frappe.log_error(
		title=f"Integration failed: {request.integration_request_service} {request.request_description}",
		message=frappe.get_traceback(with_context=True),
		reference_doctype="Integration Request",
		reference_name=request.name,
	)


def redact(value):
	if isinstance(value, dict):
		return {k: REDACTED if SENSITIVE.search(str(k)) else redact(v) for k, v in value.items()}

	if isinstance(value, list | tuple):
		return [redact(v) for v in value]

	return value
