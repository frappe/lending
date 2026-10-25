# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The checks a borrower passes on the portal: PAN, KYC, bank account and eSign.

Each check is a provider type with its own adapter field in Loan Origination Settings. The real
adapters (NSDL or Surepass for PAN, DigiLocker through Digio, a penny drop, Aadhaar eSign) belong
in the app that holds the vendor's credentials, like the credit bureau adapters.
"""

import frappe
from frappe import _

from lending.loan_integrations import log
from lending.loan_integrations.adapters import get_adapter
from lending.loan_integrations.base import BaseAdapter, IntegrationError, Refused

SETTINGS = "Loan Origination Settings"

PAN = "PAN Verification"
KYC = "KYC"
BANK = "Bank Account Verification"
ESIGN = "eSign"

ADAPTER_FIELDS = {
	PAN: "pan_verification_adapter",
	KYC: "kyc_adapter",
	BANK: "bank_verification_adapter",
	ESIGN: "esign_adapter",
}


class PanAdapter(BaseAdapter):
	provider_type = PAN

	def verify_pan(self, context: dict) -> dict:
		"""`pan` and `name`. Returns `verified`, `name_on_pan` and `reference`."""
		raise NotImplementedError


class KycAdapter(BaseAdapter):
	"""A KYC the borrower completes on the provider's own page, such as DigiLocker."""

	provider_type = KYC

	def start(self, context: dict) -> dict:
		"""`name`, `mobile` and `return_url`. Returns `request_id` and the `redirect_url` to send the borrower to."""
		raise NotImplementedError

	def fetch(self, context: dict) -> dict:
		"""`request_id`. Returns `status` (Pending, Verified or Rejected), `reference`, `name`,
		`date_of_birth` and `address`."""
		raise NotImplementedError


class BankVerificationAdapter(BaseAdapter):
	provider_type = BANK

	def verify(self, context: dict) -> dict:
		"""`account_number`, `ifsc` and `name`. Returns `verified`, `name_at_bank`, `bank_name` and `reference`."""
		raise NotImplementedError


class ESignAdapter(BaseAdapter):
	"""Aadhaar eSign: the borrower signs a document with an OTP sent to their Aadhaar mobile."""

	provider_type = ESIGN

	def send_otp(self, context: dict) -> dict:
		"""`file_url` of the PDF and the `signer`'s name and mobile. Returns `request_id`."""
		raise NotImplementedError

	def sign(self, context: dict) -> dict:
		"""`request_id` and `otp`. Returns `reference`."""
		raise NotImplementedError


def adapter_key(provider_type: str) -> str | None:
	return frappe.db.get_single_value(SETTINGS, ADAPTER_FIELDS[provider_type])


def call(provider_type: str, operation: str, context: dict, doc) -> dict:
	"""Log the call as an Integration Request, then return the adapter's answer, or raise Refused."""
	key = adapter_key(provider_type)
	if not key:
		frappe.throw(_("{0} is not set up yet. Please contact us.").format(_(provider_type)))

	adapter = get_adapter(key)
	request = log.start(
		service=key,
		operation=operation,
		context=context,
		reference_doctype=doc.doctype,
		reference_docname=doc.name,
		url=adapter.target_url(),
	)

	try:
		output = getattr(adapter, operation)(context)
	except IntegrationError as e:
		log.fail(request, e)
		raise Refused(str(e)) from e

	log.succeed(request, output)
	return output
