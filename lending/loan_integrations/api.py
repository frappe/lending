# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from lending.loan_integrations import log
from lending.loan_integrations.adapters import get_adapter

SAVEPOINT = "lending_integration_call"


def run_integration(provider: str, context: dict, reference_doc, operation: str) -> dict:
	adapter = get_adapter(provider)

	existing = log.find_existing(provider, operation, reference_doc.doctype, reference_doc.name)

	if existing and existing.status == "Completed":
		return {
			"request": existing.name,
			"status": "Completed",
			"output": log.stored_output(existing),
		}

	if existing and existing.status != "Failed":
		# Open, so whether the provider answered is unknown — not a thing to guess at for a
		# call that is billed and permanent. A person settles the row, then this runs again.
		frappe.throw(
			_("A {0} call for {1} is still open as {2}. Settle that request before asking again.").format(
				operation, reference_doc.name, existing.name
			),
			title=_("Call Already In Flight"),
		)

	request = log.start(
		provider=provider,
		operation=operation,
		context=context,
		reference_doctype=reference_doc.doctype,
		reference_docname=reference_doc.name,
		url=adapter.target_url(),
	)
	frappe.db.savepoint(SAVEPOINT)

	try:
		parsed = adapter.parse(adapter.pull(context))
		extra = adapter.persist(request, parsed, context)
	except Exception as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		log.fail(request, e)

		return {"request": request.name, "status": "Failed", "error": str(e)}

	frappe.db.release_savepoint(SAVEPOINT)
	output = log.succeed(request, parsed, extra)
	return {"request": request.name, "status": "Completed", "output": output}
