# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from lending.loan_integrations import log
from lending.loan_integrations.adapters import get_adapter

SAVEPOINT = "lending_integration_call"


def run_integration(adapter_key: str, context: dict, reference_doc, operation: str) -> dict:
	adapter = get_adapter(adapter_key)

	existing = log.find_existing(adapter_key, operation, reference_doc.doctype, reference_doc.name)

	if existing and existing.status == "Completed":
		return {
			"request": existing.name,
			"status": "Completed",
			"output": log.stored_output(existing),
		}

	if existing and existing.status != log.FAILED:
		# Either the provider's answer never arrived or it arrived and we could not store it.
		# Neither is a thing to guess at for a call that is billed and permanent, so a person
		# settles the row and only then does this run again.
		frappe.throw(
			_("A {0} call for {1} is still open as {2}. Settle that request before asking again.").format(
				operation, reference_doc.name, existing.name
			),
			title=_("Call Already In Flight"),
		)

	request = log.start(
		service=adapter_key,
		operation=operation,
		context=context,
		reference_doctype=reference_doc.doctype,
		reference_docname=reference_doc.name,
		url=adapter.target_url(),
	)
	frappe.db.savepoint(SAVEPOINT)

	try:
		response = adapter.pull(context)
	except Exception as e:
		# Nothing came back, so there is nothing to lose by asking again.
		frappe.db.rollback(save_point=SAVEPOINT)
		log.fail(request, e)

		return {"request": request.name, "status": log.FAILED, "error": str(e)}

	parsed = None

	try:
		parsed = adapter.parse(response)
		extra = adapter.persist(request, parsed, context)
	except Exception as e:
		# The provider answered, so the enquiry is spent whether or not we made sense of it.
		frappe.db.rollback(save_point=SAVEPOINT)
		log.leave_unrecorded(request, e, parsed)

		return {"request": request.name, "status": log.UNRECORDED, "error": str(e)}

	frappe.db.release_savepoint(SAVEPOINT)
	output = log.succeed(request, parsed, extra)
	return {"request": request.name, "status": "Completed", "output": output}
