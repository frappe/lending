# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Stand-ins for the PAN, KYC, bank and eSign providers, registered only in developer mode.

They check formats and OTPs the way a provider would, and answer from the borrower's own
records, so a demo runs the whole portal journey without credentials.
"""

import re

import frappe
from frappe.utils import add_years, getdate

from lending.loan_integrations.base import IntegrationError
from lending.loan_integrations.verification import (
	BankVerificationAdapter,
	ESignAdapter,
	KycAdapter,
	PanAdapter,
)

OTP = "123456"
PAN_FORMAT = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_FORMAT = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
# The page the sample KYC sends the borrower to, standing in for DigiLocker.
CONSENT_ROUTE = "/borrower-portal/kyc-consent"
CONSENT_KEY = "portal-apply-sample-kyc"
BANKS = {
	"HDFC": "HDFC Bank",
	"ICIC": "ICICI Bank",
	"SBIN": "State Bank of India",
	"UTIB": "Axis Bank",
	"KKBK": "Kotak Mahindra Bank",
}


def reference(prefix: str) -> str:
	return f"{prefix}-{frappe.generate_hash(length=10).upper()}"


def check_otp(context):
	if context.get("otp") != OTP:
		raise IntegrationError("The OTP is wrong or has expired")


class SamplePanAdapter(PanAdapter):
	key = "Sample PAN Verification"

	def verify_pan(self, context):
		pan = (context.get("pan") or "").upper()
		if not PAN_FORMAT.match(pan):
			raise IntegrationError("This is not a valid PAN")

		return {"verified": True, "name_on_pan": (context.get("name") or "").upper(), "reference": reference("PAN")}


class SampleKycAdapter(KycAdapter):
	key = "Sample KYC"

	def start(self, context):
		request_id = reference("KYC")
		frappe.cache.set_value(f"{CONSENT_KEY}:{request_id}", {"name": context.get("name")}, expires_in_sec=3600)

		return {"request_id": request_id, "redirect_url": f"{CONSENT_ROUTE}?request={request_id}"}

	def fetch(self, context):
		request = frappe.cache.get_value(f"{CONSENT_KEY}:{context.get('request_id')}")
		if not request:
			raise IntegrationError("This KYC request has expired. Please start again")
		if not request.get("consented"):
			return {"status": "Pending"}

		return {
			"status": "Verified",
			"reference": context.get("request_id"),
			"name": request.get("name"),
			"date_of_birth": str(add_years(getdate(), -35)),
			"address": "12 MG Road, Bengaluru, Karnataka 560001",
		}


def give_consent(request_id: str):
	"""What the borrower's Allow on DigiLocker does: the next fetch answers Verified."""
	key = f"{CONSENT_KEY}:{request_id}"
	request = frappe.cache.get_value(key)
	if not request:
		raise IntegrationError("This KYC request has expired. Please start again")

	frappe.cache.set_value(key, {**request, "consented": True}, expires_in_sec=3600)


class SampleBankVerificationAdapter(BankVerificationAdapter):
	key = "Sample Bank Account Verification"

	def verify(self, context):
		ifsc = (context.get("ifsc") or "").upper()
		if not IFSC_FORMAT.match(ifsc):
			raise IntegrationError("This is not a valid IFSC")
		if not re.fullmatch(r"[0-9]{9,18}", context.get("account_number") or ""):
			raise IntegrationError("An account number has 9 to 18 digits")

		return {
			"verified": True,
			"name_at_bank": context.get("name"),
			"bank_name": BANKS.get(ifsc[:4], "Sample Bank"),
			"reference": reference("PENNY"),
		}


class SampleESignAdapter(ESignAdapter):
	key = "Sample eSign"

	def send_otp(self, context):
		return {"request_id": reference("ESIGN")}

	def sign(self, context):
		check_otp(context)
		return {"reference": context.get("request_id")}
