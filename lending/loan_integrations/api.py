# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

from lending.loan_integrations import log
from lending.loan_integrations.adapters import get_adapter

SAVEPOINT = "lending_integration_call"


def run_integration(provider: str, context: dict, reference_doc, operation: str) -> dict:
	"""Call one provider, and leave exactly one Integration Request in a terminal status.

	A provider that answers badly is a recorded outcome, not an exception. Frappe rolls the
	whole transaction back when an exception escapes a request, so raising here would delete
	the Failed row we had just written: the successes would be logged and the failures would
	vanish. Callers read the returned status instead.
	"""
	adapter = get_adapter(provider)

	existing = log.find_existing(provider, operation, reference_doc.doctype, reference_doc.name)

	if existing:
		status = frappe.db.get_value("Integration Request", existing, "status")

		return {"request": existing, "status": status}

	request = log.start(
		provider=provider,
		operation=operation,
		context=context,
		reference_doctype=reference_doc.doctype,
		reference_docname=reference_doc.name,
		url=adapter.get_base_url(),
	)

	# The savepoint is what lets us record the failure: it rewinds whatever the adapter half
	# wrote before it broke, without discarding the request row opened above it.
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

	# The caller gets what persist() wrote as well as what the provider said, because the
	# document a pull produced is usually the thing the caller came for.
	return {"request": request.name, "status": "Completed", "output": output}
