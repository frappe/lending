# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import nowdate

from lending.collateral.mutual_fund.nav_file import fill_prices, validate_price_update
from lending.collateral.mutual_fund.registry import NAV_FIELD, SETTINGS, call, get_adapter_key


def update_navs():
	"""Daily: price every mutual fund type from the NAV adapter's file, once per NAV date."""
	if not get_adapter_key(NAV_FIELD):
		return

	content = fetch_nav_file()
	if not content:
		return

	price_date = get_latest_nav_date(content)
	if not price_date:
		return

	for security_type in frappe.get_all("Loan Security Type", {"is_mutual_fund": 1}, pluck="name"):
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
	"""Fill the form's prices from the NAV adapter, as Read AMFI NAV File does from an upload."""
	doc = frappe.get_doc(frappe.parse_json(doc))
	doc.check_permission("write")
	validate_price_update(doc)

	content = fetch_nav_file()
	if not content:
		return None

	filled = fill_prices(doc, content)
	doc.save()
	return {"name": doc.name, "filled": filled}


def get_latest_nav_date(content):
	latest = None
	for line in content.splitlines():
		fields = line.split(";")
		if len(fields) < 6 or not fields[0].strip().isdigit():
			continue
		try:
			nav_date = datetime.strptime(fields[-1].strip(), "%d-%b-%Y").date()
		except ValueError:
			continue
		latest = max(latest or nav_date, nav_date)
	return latest
