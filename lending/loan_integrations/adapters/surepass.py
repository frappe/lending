# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint

from lending.loan_integrations.adapters import register
from lending.loan_integrations.base import IntegrationError
from lending.loan_integrations.bureau import BureauAdapter

# Surepass answers HTTP 200 and reports the real outcome in the body, so the status line
# alone never says whether a call worked.
SUCCESS_CODE = 200

# The signed link Surepass returns carries an AWS key and signature in its query string, and
# expires in ten minutes. We download the PDF during the call and drop the URL, rather than
# writing somebody else's credentials into our own logs.
DROPPED_FROM_PAYLOAD = ("credit_report_link", "credit_report_base64")

# CIBIL answers below the scoring floor to say why it could not score, rather than to score
# badly: -1 is no history at all, 1 to 5 too little of it. Treating those as a score would
# read "no credit history" as "the worst possible borrower".
LOWEST_REAL_SCORE = 300


class SurepassBureauAdapter(BureauAdapter):
	"""Surepass, who resell several bureaux behind one API.

	Every bureau they carry shares this envelope, this authentication and this request body,
	so a new one is the endpoint and the bureau name and nothing else.
	"""

	# The path under the provider's base URL, and the Credit Bureau Report option it fills in.
	endpoint: str = ""

	def auth_headers(self) -> dict:
		_, token = self.creds()

		if not token:
			frappe.throw(_("Set the API Secret on {0} to its Surepass token.").format(self.provider.name))

		return {
			"Content-Type": "application/json",
			"Accept": "application/json",
			"Authorization": f"Bearer {token}",
		}

	def pull(self, context: dict) -> dict:
		return self.request("POST", self.endpoint, json=self.request_body(context))

	def request_body(self, context: dict) -> dict:
		# "Y" is an assertion that the applicant agreed, so it is only ever sent because the
		# caller already checked that they did. Hardcoding it would make us claim a consent
		# nobody gave. See validate_bureau_consent.
		return {
			"name": context.get("name"),
			"pan": context.get("pan"),
			"mobile": context.get("mobile"),
			"gender": (context.get("gender") or "").lower(),
			"consent": "Y",
		}

	def parse(self, response: dict) -> dict:
		if not response.get("success") or cint(response.get("status_code")) != SUCCESS_CODE:
			raise IntegrationError(
				_("{0} refused the request: {1}").format(
					self.provider.name, response.get("message") or _("no reason given")
				)
			)

		data = response.get("data") or {}
		score = cint(data.get("credit_score"))

		return {
			"external_id": data.get("client_id"),
			"score": score if score >= LOWEST_REAL_SCORE else 0,
			# Surepass's report endpoints answer with a score and a document. Neither carries
			# the applicant's existing obligations, so we say we do not know them rather than
			# let an unfilled field be read as an applicant who owes nothing.
			"obligations_known": False,
			"total_emi": 0,
			"report_url": data.get("credit_report_link"),
			"payload": {k: v for k, v in data.items() if k not in DROPPED_FROM_PAYLOAD},
		}


@register
class SurepassCibilAdapter(SurepassBureauAdapter):
	key = "Surepass CIBIL"
	bureau = "CIBIL"
	endpoint = "/credit-report-cibil/fetch-report-pdf"
