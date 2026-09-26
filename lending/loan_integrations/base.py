# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import base64
import json
from functools import cached_property

import frappe
from frappe import _
from frappe.utils import get_request_session


class IntegrationError(Exception):
	pass


class RateLimited(IntegrationError):
	def __init__(self, message, retry_after=None):
		super().__init__(message)
		self.retry_after = retry_after


class BaseAdapter:
	provider_type: str = ""
	key: str = ""
	settings_doctype: str = ""

	@cached_property
	def settings(self):
		if not self.settings_doctype:
			frappe.throw(
				_("{0} names no settings doctype, so there is nowhere to read its credentials from.").format(
					self.key
				)
			)

		return frappe.get_cached_doc(self.settings_doctype)

	def pull(self, context: dict) -> dict:
		raise NotImplementedError

	def parse(self, response: dict) -> dict:
		raise NotImplementedError

	def persist(self, request, parsed: dict, context: dict) -> dict | None:
		return None

	# Settings belong to whichever app owns the vendor, so every field is read with .get():
	# attribute access turns a field nobody added into an AttributeError mid-call.
	def environment(self) -> str:
		if self.settings.get("enable_production"):
			return "production"

		if self.settings.get("enable_sandbox"):
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
		try:
			return self.get_base_url()
		except frappe.ValidationError:
			return None

	def cred(self, fieldname: str) -> str | None:
		return self.settings.get_password(fieldname, raise_exception=False)

	def creds(self) -> tuple[str | None, str | None]:
		prefix = "" if self.environment() == "production" else "sandbox_"

		return self.cred(f"{prefix}api_client_id"), self.cred(f"{prefix}api_secret")

	def config(self, key: str, default=None):
		extra_config = self.settings.get("extra_config")

		if not extra_config:
			return default

		return json.loads(extra_config).get(key, default)

	def auth_headers(self) -> dict:
		client_id, secret = self.creds()

		if not (client_id and secret):
			frappe.throw(
				_("No API credentials are set in {0} for the {1} environment.").format(
					self.settings.name, self.environment()
				)
			)

		return {
			"Content-Type": "application/json",
			"Accept": "application/json",
			"Authorization": "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode(),
		}

	def request(self, method: str, path: str, headers: dict | None = None, **kwargs):
		session = get_request_session(max_retries=0)
		url = f"{self.get_base_url()}{path}"

		response = session.request(
			method,
			url,
			headers={**self.auth_headers(), **(headers or {})},
			timeout=self.settings.get("timeout") or 30,
			**kwargs,
		)

		if response.status_code == 429:
			raise RateLimited(
				_("{0} is rate limiting us.").format(self.key),
				retry_after=response.headers.get("Retry-After"),
			)

		response.raise_for_status()

		return response.json() if response.content else {}
