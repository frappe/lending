# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

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
		"""`name`, `mobile`, the verified `pan` and `return_url`. Returns `request_id` and the
		`redirect_url` to send the borrower to."""
		raise NotImplementedError

	def fetch(self, context: dict) -> dict:
		"""`request_id`. Returns `status` (Pending, Verified or Rejected), `reference`, `name`,
		`date_of_birth`, `address` and the `pan` the KYC found, which must match the verified one."""
		raise NotImplementedError


class BankVerificationAdapter(BaseAdapter):
	provider_type = BANK

	def verify(self, context: dict) -> dict:
		"""`account_number`, `ifsc` and `name`. Returns `verified`, `name_at_bank`, `bank_name` and `reference`."""
		raise NotImplementedError


class ESignAdapter(BaseAdapter):
	"""Aadhaar eSign on the provider's own page: the eSign rules have the borrower enter the
	Aadhaar OTP there, never on ours."""

	provider_type = ESIGN

	def start(self, context: dict) -> dict:
		"""`file_url` of the PDF, `reference`, the `signer`'s name, mobile and email, and `return_url`.
		Returns `request_id` and the `redirect_url` to send the borrower to."""
		raise NotImplementedError

	def fetch(self, context: dict) -> dict:
		"""`request_id`. Returns `status` (Pending, Signed or Rejected) and `reference`."""
		raise NotImplementedError

	def download(self, context: dict) -> bytes | None:
		"""`request_id`. Returns the signed PDF, or None to keep the letter as it was."""
		return None


def adapter_key(provider_type: str) -> str | None:
	return frappe.db.get_single_value(SETTINGS, ADAPTER_FIELDS[provider_type])


def adapter(provider_type: str):
	key = adapter_key(provider_type)
	if not key:
		frappe.throw(_("{0} is not set up yet. Please contact us.").format(_(provider_type)))

	return get_adapter(key)


def call(provider_type: str, operation: str, context: dict, doc) -> dict:
	provider = adapter(provider_type)
	request = log.start(
		service=provider.key,
		operation=operation,
		context=context,
		reference_doctype=doc.doctype,
		reference_docname=doc.name,
		url=provider.target_url(),
	)

	try:
		output = getattr(provider, operation)(context)
	except IntegrationError as e:
		log.fail(request, e)
		raise Refused(str(e)) from e

	log.succeed(request, output)
	return output
