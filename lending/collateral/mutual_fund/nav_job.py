# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from lending.collateral.mutual_fund.nav_file import fill_prices, validate_price_update
from lending.collateral.mutual_fund.registry import NAV_FIELD, SETTINGS, call, get_adapter_key


def update_navs():
	if not get_adapter_key(NAV_FIELD):
		return

	content = fetch_nav_file()
	if not content:
		return

	for security_type in frappe.get_all("Loan Security Type", {"is_mutual_fund": 1}, pluck="name"):
		# Liquid and overnight funds also publish a NAV for weekends and holidays, so a type that holds
		# them beside other funds needs one update for each date, or the other funds lose a day's price
		for price_date in get_nav_dates(content, get_pledged_scheme_codes(security_type)):
			try:
				create_price_update(security_type, price_date, content)
			except Exception:
				frappe.log_error(title=_("Mutual fund NAV update failed for {0}").format(security_type))


def fetch_nav_file():
	output = call(NAV_FIELD, "fetch_nav_file", {"date": nowdate()}, frappe.get_single(SETTINGS))
	return output and output.get("content")


def create_price_update(security_type, price_date, content):
	if frappe.db.exists(
		"Loan Security Price Update",
		{"loan_security_type": security_type, "price_date": price_date, "docstatus": ("<", 2)},
	):
		return None

	update = frappe.new_doc("Loan Security Price Update")
	update.loan_security_type = security_type
	update.price_date = price_date
	update.get_securities()
	if not update.items:
		return None

	fill_prices(update, content)
	update.insert(ignore_permissions=True)
	update.submit()
	return update.name


@frappe.whitelist(methods=["POST"])
def fetch_latest_nav(doc: str | dict):
	doc = frappe.get_doc(frappe.parse_json(doc))
	doc.check_permission("write")
	validate_price_update(doc)

	content = fetch_nav_file()
	if not content:
		return None

	filled = fill_prices(doc, content)
	doc.save()
	return {"name": doc.name, "filled": filled}


def get_pledged_scheme_codes(security_type):
	# The same securities an update prices, so a date found here always fills at least one row
	update = frappe.new_doc("Loan Security Price Update")
	update.loan_security_type = security_type
	securities = update.get_pledged_securities()
	if not securities:
		return set()

	codes = frappe.get_all(
		"Loan Security",
		filters={"name": ("in", list(securities)), "amfi_scheme_code": ("is", "set")},
		pluck="amfi_scheme_code",
	)
	return {code.strip() for code in codes}


def get_nav_dates(content, scheme_codes):
	latest = {}
	for line in content.splitlines():
		fields = line.split(";")
		code = fields[0].strip()
		if len(fields) < 6 or code not in scheme_codes or flt(fields[-2]) <= 0:
			continue
		try:
			nav_date = datetime.strptime(fields[-1].strip(), "%d-%b-%Y").date()
		except ValueError:
			continue
		latest[code] = max(latest.get(code, nav_date), nav_date)

	# Oldest first, so each later update ends the price the one before it set
	return sorted(set(latest.values()))
