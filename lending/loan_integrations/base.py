# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import base64
import json
from functools import cached_property

import frappe
from frappe import _
from frappe.utils import get_request_session


class IntegrationError(Exception):
	"""Raised when a provider answers, but not with what we asked for."""


class RateLimited(IntegrationError):
	"""Raised on a 429 so the caller can wait as long as the provider asked."""

	def __init__(self, message, retry_after=None):
		super().__init__(message)
		self.retry_after = retry_after


class BaseAdapter:
	"""Translates between our vocabulary and one provider's.

	Subclasses implement pull/parse, and persist when the result belongs in a document of
	its own. Everything else here is the plumbing every provider needs: which environment
	to talk to, which credentials to use, and how to make the call.
	"""

	provider_type: str = ""
	key: str = ""

	# The doctype holding this vendor's own URLs and credentials. It belongs to whichever app
	# owns the vendor, which is why this app never names one: lending knows that a provider
	# exists and which adapter answers for it, and nothing about how to authenticate to it.
	settings_doctype: str = ""

	def __init__(self, provider_doc):
		self.provider = provider_doc

	@cached_property
	def settings(self):
		"""The vendor's own settings document, read the first time something needs it.

		Lazily, so an adapter that never reaches the network — a test double, or one
		answering from a report we already hold — does not require credentials to exist.
		"""
		if not self.settings_doctype:
			frappe.throw(
				_("{0} names no settings doctype, so there is nowhere to read its credentials from.").format(
					self.provider.name
				)
			)

		return frappe.get_cached_doc(self.settings_doctype)

	# The interface each adapter implements.

	def pull(self, context: dict) -> dict:
		raise NotImplementedError

	def parse(self, response: dict) -> dict:
		raise NotImplementedError

	def persist(self, request, parsed: dict, context: dict) -> dict | None:
		"""Write the result wherever it belongs, and return anything worth logging.

		Takes the context back because the response says what was found, while the context
		says who it was found about, and a stored result usually needs both.

		Returning None keeps the dispatcher generic: it never has to ask what kind of
		provider it is holding.
		"""
		return None

	# Environment and credentials.

	def environment(self) -> str:
		# Production wins when both are enabled, matching how ekyc_india reads Digio Settings.
		if self.settings.enable_production:
			return "production"

		if self.settings.enable_sandbox:
			return "sandbox"

		frappe.throw(
			_("Enable either Sandbox or Production in {0} before calling it.").format(self.settings.name)
		)

	def get_base_url(self) -> str:
		fieldname = "production_url" if self.environment() == "production" else "sandbox_url"
		url = self.settings.get(fieldname)

		if not url:
			frappe.throw(
				_("{0} is not set in {1}.").format(
					frappe.get_meta(self.settings.doctype).get_label(fieldname), self.settings.name
				)
			)

		return url.rstrip("/")

	def target_url(self) -> str | None:
		"""Where this call is headed, for the log to record before we place it.

		The address is wanted by the log, not by the call, so a provider nobody has finished
		configuring must not raise from here: that would escape before a row had been written
		and leave the one outcome worth keeping — a failure — with no record at all. The same
		misconfiguration is reported by the call itself a few lines later, where it is caught
		and logged like any other way of not getting an answer.
		"""
		try:
			return self.get_base_url()
		except frappe.ValidationError:
			return None

	def cred(self, fieldname: str) -> str | None:
		return self.settings.get_password(fieldname, raise_exception=False)

	def creds(self) -> tuple[str | None, str | None]:
		"""The client id and secret for the environment we are pointed at."""
		prefix = "" if self.environment() == "production" else "sandbox_"

		return self.cred(f"{prefix}api_client_id"), self.cred(f"{prefix}api_secret")

	def config(self, key: str, default=None):
		if not self.settings.extra_config:
			return default

		return json.loads(self.settings.extra_config).get(key, default)

	def auth_headers(self) -> dict:
		client_id, secret = self.creds()

		return {
			"Content-Type": "application/json",
			"Accept": "application/json",
			"Authorization": "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode(),
		}

	# The call itself.

	def request(self, method: str, path: str, headers: dict | None = None, **kwargs):
		"""Make one HTTP call and return the decoded body.

		Deliberately not frappe.integrations.utils.make_request: that sets no timeout, so a
		provider that accepts the connection and then goes quiet holds the worker until the
		gateway gives up. It also mounts a retry adapter that repeats a 500 five times, which
		for a bureau means five billable pulls behind one call. Retries belong where they can
		be counted, not inside a single request.
		"""
		session = get_request_session(max_retries=0)
		url = f"{self.get_base_url()}{path}"

		response = session.request(
			method,
			url,
			headers={**self.auth_headers(), **(headers or {})},
			timeout=self.settings.timeout or 30,
			**kwargs,
		)

		if response.status_code == 429:
			raise RateLimited(
				_("{0} is rate limiting us.").format(self.provider.name),
				retry_after=response.headers.get("Retry-After"),
			)

		response.raise_for_status()

		return response.json() if response.content else {}
