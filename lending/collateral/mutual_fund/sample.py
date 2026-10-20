# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Stand-ins for MFCentral and the AMFI download, registered only in developer mode.

They answer from the site's own mutual fund securities, so every demo site has holdings that match.
"""

import hashlib

import frappe
from frappe.utils import add_days, add_years, flt, getdate, nowdate

from lending.collateral.mutual_fund.registry import NavAdapter, RegistryAdapter
from lending.loan_integrations.base import IntegrationError
from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)

OTP = "123456"
UNLISTED_SCHEME = {"amfi_scheme_code": "199999", "scheme_name": "Sample Small Cap Fund - Direct Plan - Growth"}
REDEMPTION_DISCOUNT = 0.98
EXIT_LOAD = 0.01
STT = 0.00001


def digest(*parts):
	return int(hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest(), 16)


def reference(prefix, *parts):
	return f"{prefix}-{digest(*parts, frappe.generate_hash(length=6)) % 10**8:08d}"


def check_otp(context):
	if context.get("otp") != OTP:
		raise IntegrationError("The OTP is wrong or has expired")


def get_mutual_fund_securities():
	return frappe.get_all(
		"Loan Security",
		filters={"is_mutual_fund": 1, "disabled": 0, "amfi_scheme_code": ("is", "set")},
		fields=["name", "loan_security_name", "amfi_scheme_code", "lock_in_days"],
		order_by="name",
	)


class SampleRegistryAdapter(RegistryAdapter):
	key = "Sample Mutual Fund Registry"

	def send_otp(self, context):
		return {"request_id": reference("CAS", context.get("pan"))}

	def fetch_holdings(self, context):
		check_otp(context)
		pan = context.get("pan") or ""
		folio = f"{digest(pan) % 10**8:08d}/{digest(pan, 'check') % 100:02d}"
		holdings = [self.get_holding(security, pan, folio) for security in get_mutual_fund_securities()]
		holdings.append(
			{
				**UNLISTED_SCHEME,
				"folio_number": folio,
				"units": 750.0,
				"free_units": 750.0,
				"holding_mode": "Statement of Account",
				"holding_type": "Single",
				"lots": [{"purchase_date": str(add_years(nowdate(), -1)), "units": 750.0}],
			}
		)
		return {"holdings": holdings}

	def get_holding(self, security, pan, folio):
		units = flt(500 + digest(pan, security.amfi_scheme_code) % 4500)
		if security.lock_in_days:
			# One lot is past its lock-in and one is still inside it
			free_lot = round(units * 0.6)
			lots = [
				{"purchase_date": str(add_years(nowdate(), -4)), "units": free_lot},
				{"purchase_date": str(add_days(nowdate(), -180)), "units": units - free_lot},
			]
		else:
			lots = [{"purchase_date": str(add_years(nowdate(), -2)), "units": units}]

		return {
			"amfi_scheme_code": security.amfi_scheme_code,
			"scheme_name": security.loan_security_name or security.name,
			"folio_number": folio,
			"units": units,
			"free_units": units - get_pledged_units(security.name, folio),
			"holding_mode": "Statement of Account",
			"holding_type": "Single",
			"lots": lots,
		}

	def mark_lien(self, context):
		return {"request_id": reference("LIENREQ", context.get("pan"))}

	def confirm_lien(self, context):
		check_otp(context)
		return {
			"liens": [
				{"row": line["row"], "lien_reference": reference("LIEN", line["folio_number"])}
				for line in context.get("lines") or []
			]
		}

	def revoke_lien(self, context):
		return {
			"releases": [
				{"row": line["row"], "release_reference": reference("REVOKE", line["amfi_scheme_code"])}
				for line in context.get("lines") or []
			]
		}

	def invoke_lien(self, context):
		items = []
		for item in context.get("items") or []:
			nav = flt(flt(get_loan_security_price(item["loan_security"])) * REDEMPTION_DISCOUNT, 4)
			value = flt(item["units"]) * nav
			items.append(
				{
					"loan_security": item["loan_security"],
					"units": flt(item["units"]),
					"nav": nav,
					"exit_load": flt(value * EXIT_LOAD, 2),
					"stt": flt(value * STT, 2),
				}
			)
		return {"redemption_reference": reference("RED", context.get("loan")), "items": items}


class SampleNavAdapter(NavAdapter):
	key = "Sample Mutual Fund NAV"

	def fetch_nav_file(self, context):
		nav_date = last_weekday(getdate(context.get("date") or nowdate()))
		lines = [
			"Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date",
			" ",
			"Open Ended Schemes(Sample)",
			" ",
		]
		for security in frappe.get_all(
			"Loan Security",
			filters={"is_mutual_fund": 1, "disabled": 0, "amfi_scheme_code": ("is", "set")},
			fields=["name", "loan_security_name", "amfi_scheme_code"],
		):
			price = flt(get_loan_security_price(security.name))
			if not price:
				continue
			# Up to 1% up or down a day, the same answer for the same day
			drift = (digest(security.amfi_scheme_code, nav_date) % 201 - 100) / 10000
			nav = flt(price * (1 + drift), 4)
			lines.append(
				f"{security.amfi_scheme_code};-;-;{security.loan_security_name or security.name};Direct Plan;Growth;{nav};{nav_date.strftime('%d-%b-%Y')}"
			)
		return {"content": "\r\n".join(lines)}


def last_weekday(date):
	while date.weekday() > 4:
		date = add_days(date, -1)
	return getdate(date)


def get_pledged_units(loan_security, folio):
	pledge = frappe.qb.DocType("Pledge")
	assignment = frappe.qb.DocType("Loan Security Assignment")
	units = (
		frappe.qb.from_(pledge)
		.inner_join(assignment)
		.on(pledge.parent == assignment.name)
		.select(pledge.qty)
		.where(assignment.docstatus == 1)
		.where(assignment.status == "Pledged")
		.where(pledge.loan_security == loan_security)
		.where(pledge.folio_number == folio)
		.run(pluck=True)
	)
	return sum(flt(qty) for qty in units)
