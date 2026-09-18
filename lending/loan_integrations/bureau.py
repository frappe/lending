# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

from requests.adapters import HTTPAdapter

import frappe
from frappe import _
from frappe.utils import cint, get_request_session, now_datetime

from lending.loan_integrations import log
from lending.loan_integrations.api import run_integration
from lending.loan_integrations.base import BaseAdapter, IntegrationError

PROVIDER_TYPE = "Credit Bureau"
OPERATION = "Credit Bureau Pull"
LOAN_LEAD = "Loan Lead"
REPORT = "Credit Bureau Report"

MAX_REPORT_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3

ATTACHMENT_SAVEPOINT = "lending_bureau_attachment"


class BureauAdapter(BaseAdapter):
	provider_type = PROVIDER_TYPE

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
		report.insert(ignore_permissions=True)
		report.report_pdf = self.attach_report(report, parsed.get("report_url"))
		report.submit()
		return {"credit_bureau_report": report.name, "score": report.score}

	def attach_report(self, report, url: str | None) -> str | None:
		if not url:
			return None

		content = fetch_document(url)
		if not content:
			return None

		frappe.db.savepoint(ATTACHMENT_SAVEPOINT)

		try:
			file = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"{report.name}.pdf",
					"attached_to_doctype": report.doctype,
					"attached_to_name": report.name,
					"attached_to_field": "report_pdf",
					"content": content,
					"is_private": 1,
				}
			).insert(ignore_permissions=True)
		except Exception:
			frappe.db.rollback(save_point=ATTACHMENT_SAVEPOINT)
			frappe.log_error(
				title=f"Could not attach the bureau report to {report.name}",
				message=frappe.get_traceback(),
			)

			return None

		frappe.db.release_savepoint(ATTACHMENT_SAVEPOINT)

		return file.file_url


def fetch_document(url: str) -> bytes | None:
	try:
		content = download_document(url)
	except Exception:
		frappe.log_error(
			title="Could not fetch the bureau report document",
			message=f"{unsigned(url)}\n\n{frappe.get_traceback()}",
		)

		return None

	if len(content) > MAX_REPORT_BYTES:
		frappe.log_error(
			title="Bureau report document was too large to store",
			message=f"{unsigned(url)} answered with more than {MAX_REPORT_BYTES} bytes.",
		)

		return None

	return content


def unsigned(url: str) -> str:
	parsed = urlparse(url)

	return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def download_document(url: str) -> bytes:
	for _hop in range(MAX_REDIRECTS + 1):
		response = get_vetted_document(url)

		if not response.is_redirect:
			response.raise_for_status()

			return response.raw.read(MAX_REPORT_BYTES + 1, decode_content=True)

		url = urljoin(url, response.headers["Location"])

	raise IntegrationError(
		_("The bureau report link redirected more than {0} times.").format(MAX_REDIRECTS)
	)


def get_vetted_document(url: str):
	"""Ask the address the hostname was vetted at, rather than the hostname.

	Vetting the name and then leaving the request to look it up again leaves room for the answer
	to change in between, which is how a link that resolved to a public address the first time
	reaches something inside our own network the second. The hostname still travels along for the
	Host header and the certificate, so nothing else about the request changes.
	"""
	parsed = urlparse(url)
	address = validate_document_url(url)

	session = get_request_session(max_retries=0)
	session.mount("https://", PinnedHostAdapter(parsed.hostname))

	return session.get(
		parsed._replace(netloc=authority(address, parsed.port)).geturl(),
		headers={"Host": authority(parsed.hostname, parsed.port)},
		timeout=30,
		stream=True,
		allow_redirects=False,
	)


class PinnedHostAdapter(HTTPAdapter):
	"""Checks the certificate against the hostname, for a request addressed to a bare address."""

	def __init__(self, hostname: str):
		self.hostname = hostname

		super().__init__(max_retries=0)

	def init_poolmanager(self, *args, **kwargs):
		kwargs["server_hostname"] = self.hostname
		kwargs["assert_hostname"] = self.hostname

		super().init_poolmanager(*args, **kwargs)


def validate_document_url(url: str) -> str:
	"""Refuse a link that points inside our own network, and answer with the address to ask."""
	parsed = urlparse(url)

	if parsed.scheme != "https":
		frappe.throw(
			_("A bureau report link must be https, not {0}.").format(parsed.scheme or _("nothing"))
		)

	# In the order the resolver ranked them, which accounts for the families this host can reach.
	addresses = [
		info[4][0]
		for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
	]

	for address in addresses:
		if not ipaddress.ip_address(address).is_global:
			frappe.throw(
				_("The bureau report link at {0} points inside our own network.").format(parsed.hostname)
			)

	return addresses[0]


def authority(host: str, port: int | None) -> str:
	host = f"[{host}]" if ":" in host else host

	return f"{host}:{port}" if port else host


def select_bureau_provider() -> str:
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
	lead = originating_lead(source)
	validate_bureau_consent(lead)

	return run_integration(
		provider=provider or select_bureau_provider(),
		context=build_pull_context(source, lead),
		# Filed against the document it was asked for: one pull per lead at the lead stage, one
		# per application at underwriting, and neither answered out of the other's log.
		reference_doc=source,
		operation=OPERATION,
	)


def originating_lead(source):
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


def run_bureau_pull_task(doc):
	doc.check_permission("write")

	result = pull_credit_bureau_report(doc)

	if result.get("status") == log.FAILED:
		frappe.msgprint(
			_("The credit bureau could not be reached. See Integration Request {0}.").format(
				result.get("request")
			),
			title=_("Bureau Pull Failed"),
			indicator="orange",
		)
	elif result.get("status") == log.UNRECORDED:
		frappe.msgprint(
			_(
				"The bureau answered but its report could not be stored, so this enquiry is already"
				" spent. Settle Integration Request {0} before anyone pulls again."
			).format(result.get("request")),
			title=_("Bureau Report Not Stored"),
			indicator="red",
		)

	return result
