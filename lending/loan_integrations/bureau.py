# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, get_request_session, now_datetime

from lending.loan_integrations.api import run_integration
from lending.loan_integrations.base import BaseAdapter

PROVIDER_TYPE = "Credit Bureau"
OPERATION = "Credit Bureau Pull"
LOAN_LEAD = "Loan Lead"
REPORT = "Credit Bureau Report"

# A report runs to a few hundred kilobytes. The cap is here so a provider that answers with
# something enormous cannot fill the disk one pull at a time.
MAX_REPORT_BYTES = 10 * 1024 * 1024


class BureauAdapter(BaseAdapter):
	"""What every credit bureau adapter has in common, whoever it talks to.

	A subclass supplies pull() and parse(); parse() returns the fields below, and everything
	after that — the report document, the PDF, the permissions — is the same for CIBIL as it
	is for CRIF, so it lives here once.

	parse() returns:
	    score               int, the bureau score
	    obligations_known   whether the provider actually told us the monthly obligations
	    total_emi           those obligations, meaningless unless obligations_known
	    external_id         the provider's reference for this pull
	    report_url          where to fetch the report document, if there is one
	    payload             the response, with anything secret already taken out
	"""

	provider_type = PROVIDER_TYPE

	# The Credit Bureau Report option this adapter fills in.
	bureau: str = ""

	def persist(self, request, parsed: dict, context: dict) -> dict:
		report = frappe.new_doc(REPORT)
		report.update(
			{
				"bureau": self.bureau,
				"report_date": now_datetime(),
				"applicant_type": context.get("applicant_type"),
				"applicant": context.get("applicant"),
				"pan": context.get("pan"),
				"external_id": parsed.get("external_id"),
				"score": cint(parsed.get("score")),
				"total_emi": parsed.get("total_emi") or 0,
				"obligations_known": cint(parsed.get("obligations_known")),
				"raw_payload": frappe.as_json(parsed.get("payload"), indent=1),
			}
		)

		# The pull is made on the applicant's behalf by a workflow, which may run as somebody
		# who can read a lead but not file a bureau report. Refusing here would lose a report
		# we have already paid for and already put on the applicant's credit file.
		report.insert(ignore_permissions=True)

		# Set by hand rather than left to the attachment's own write to the parent, which the
		# submit below would overwrite from this copy of the document: the file would be
		# stored and the field pointing at it empty.
		report.report_pdf = self.attach_report(report, parsed.get("report_url"))
		report.submit()

		return {"credit_bureau_report": report.name, "score": report.score}

	def attach_report(self, report, url: str | None) -> str | None:
		"""Fetch the provider's own report document and keep our own copy.

		The link a provider hands back is normally signed and short lived — Surepass's lasts
		ten minutes — so storing the URL would leave a field that looks like evidence and is
		a dead link by the time anybody follows it.
		"""
		if not url:
			return None

		content = fetch_document(url)
		if not content:
			return None

		try:
			file = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"{report.name}.pdf",
					"attached_to_doctype": report.doctype,
					"attached_to_name": report.name,
					"attached_to_field": "report_pdf",
					"content": content,
					# Somebody's credit report is not something to serve to whoever holds the URL.
					"is_private": 1,
				}
			).insert(ignore_permissions=True)
		except Exception:
			# Frappe reads an attached PDF to check it carries no embedded JavaScript, and
			# refuses the ones it cannot read. Letting that refusal out would roll back a pull
			# we have already been billed for and already put on the applicant's credit file,
			# and the score the rules need is already saved above. So the document is the part
			# we lose, not the report.
			frappe.log_error(title=f"Could not attach the bureau report to {report.name}")

			return None

		return file.file_url


def fetch_document(url: str) -> bytes | None:
	"""Download a provider-hosted document, sending nothing of ours along with it.

	Deliberately not BaseAdapter.request(): that prepends our base URL and attaches our
	credentials, and these links point at the provider's file storage rather than at the
	provider. Sending our bearer token to somebody else's S3 bucket would hand a third party
	a key to every pull we ever make.
	"""
	try:
		response = get_request_session(max_retries=0).get(url, timeout=30, stream=True)
		response.raise_for_status()

		content = response.raw.read(MAX_REPORT_BYTES + 1, decode_content=True)
	except Exception:
		# A missing PDF is not worth losing the score over: the numbers the rules need are
		# already parsed, and the report row records that the pull happened either way.
		frappe.log_error(title="Could not fetch the bureau report document")

		return None

	if len(content) > MAX_REPORT_BYTES:
		frappe.log_error(title="Bureau report document was too large to store")

		return None

	return content


def select_bureau_provider() -> str:
	"""The one active credit bureau, or a clear answer about why there isn't one."""
	providers = frappe.get_all(
		"Loan Integration Provider",
		filters={"provider_type": PROVIDER_TYPE, "is_active": 1},
		pluck="name",
		limit=2,
	)

	if not providers:
		frappe.throw(_("No active credit bureau provider is configured."))

	if len(providers) > 1:
		frappe.throw(
			_("More than one credit bureau provider is active: {0}. Leave one active.").format(
				", ".join(providers)
			)
		)

	return providers[0]


def pull_credit_bureau_report(source, provider: str | None = None) -> dict:
	"""Pull a report for a Loan Lead or a Loan Application.

	Refuses without consent, because the call is the regulated act: by the time the report
	exists the enquiry is already on the applicant's file, and no later check can take it off.
	"""
	lead = originating_lead(source)
	validate_bureau_consent(lead)

	return run_integration(
		provider=provider or select_bureau_provider(),
		context=build_pull_context(source, lead),
		reference_doc=source,
		operation=OPERATION,
	)


def originating_lead(source):
	"""The lead an applicant was captured as, which is where their consent is recorded."""
	if source.doctype == LOAN_LEAD:
		return source

	if not source.get("loan_lead"):
		return None

	return frappe.get_doc(LOAN_LEAD, source.loan_lead)


def validate_bureau_consent(lead):
	if lead and lead.get("bureau_consent") and lead.get("bureau_consent_on"):
		return

	frappe.throw(
		_("The applicant has not consented to a credit bureau pull, so their report cannot be fetched."),
		title=_("Consent Required"),
	)


def build_pull_context(source, lead) -> dict:
	"""The applicant, in the terms every bureau asks about them in.

	An adapter translates from here into its own provider's vocabulary. Nothing below is
	specific to one bureau, which is why adding the next one touches no caller.
	"""
	lead = lead or frappe._dict()

	return {
		"name": source.get("applicant_name") or lead.get("applicant_name"),
		"pan": source.get("pan") or lead.get("pan"),
		"mobile": source.get("applicant_phone_number") or lead.get("mobile_number"),
		"gender": lead.get("gender"),
		"consent_given_on": str(lead.get("bureau_consent_on") or ""),
		"consent_version": lead.get("bureau_consent_version"),
		"applicant_type": source.get("applicant_type") if source.doctype != LOAN_LEAD else None,
		"applicant": source.get("applicant"),
	}


# A workflow task, called as method(doc). Not whitelisted: a bureau pull costs money and
# leaves a permanent enquiry on somebody's credit file, so it is not an HTTP endpoint.
def run_bureau_pull_task(doc):
	doc.check_permission("write")

	result = pull_credit_bureau_report(doc)

	if result.get("status") == "Failed":
		frappe.msgprint(
			_("The credit bureau could not be reached. See Integration Request {0}.").format(
				result.get("request")
			),
			title=_("Bureau Pull Failed"),
			indicator="orange",
		)

	return result
