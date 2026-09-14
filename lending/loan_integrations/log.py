# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe

# Everything this app writes to the shared Integration Request table is tagged with the
# provider's name, because ERPNext and india_compliance write their own rows to it too.
# url and link are in here because a provider that hands back a signed link hands back the
# credential that signs it: Surepass's report link carries an AWS key id and its signature in
# the query string. Those links are short lived and we download what they point at during the
# call, so there is nothing to gain by keeping one and a key to leak by keeping it.
SENSITIVE = re.compile(r"secret|password|otp|aadhaar|token|pin|cvv|url|link", re.IGNORECASE)
REDACTED = "***"

TERMINAL_STATUSES = ("Completed", "Failed")


def start(provider, operation, context, reference_doctype, reference_docname, url):
	"""Open an Integration Request for a call we are about to make.

	Deliberately not frappe.integrations.utils.create_request_log: that commits, which would
	also commit whatever else the caller had pending and would leak rows past a test's
	rollback. The terminal row survives because run_integration never re-raises, not because
	it was force written early.
	"""
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
	"""The call we are about to make, if it already succeeded or is still in flight.

	This is the whole idempotency mechanism, and it is why nothing may repoint the reference
	fields once a request is open: a hard bureau pull costs money and leaves a visible enquiry
	on the applicant's credit file, so it must not happen twice for one document.
	"""
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
	"""Close the request, and hand the caller what the call produced.

	What is stored goes through redact() the same way the request data does. The caller gets
	the output unredacted because it is holding it in memory already; the log is the copy
	that outlives the call, so the log is the copy that has to be safe to keep.
	"""
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
	"""Copy a payload with anything that looks like a secret replaced.

	The log has to prove what we sent without becoming the largest pile of Aadhaar numbers in
	the database.
	"""
	if isinstance(value, dict):
		return {k: REDACTED if SENSITIVE.search(str(k)) else redact(v) for k, v in value.items()}

	if isinstance(value, list | tuple):
		return [redact(v) for v in value]

	return value
