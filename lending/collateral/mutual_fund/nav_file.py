# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate


@frappe.whitelist(methods=["POST"])
def read_nav_file(doc: str | dict, file_name: str):
	"""Fill the price of each mutual fund security from an AMFI NAVAll.txt file, by its AMFI scheme code.

	Takes the form as it is, because rows from Get Securities have no price yet and cannot be saved first.
	"""
	doc = frappe.get_doc(frappe.parse_json(doc))
	validate_price_update(doc)

	file = frappe.get_doc("File", file_name)
	file.check_permission("read")
	navs = parse_nav_file(file.get_content(), getdate(doc.price_date))

	rows = {row.loan_security: row for row in doc.items}
	filled = 0
	for security in get_securities_to_price(doc, rows):
		nav = navs.get(security.amfi_scheme_code.strip())
		if not nav:
			continue
		row = rows.get(security.name) or doc.append("items", {"loan_security": security.name})
		row.price = nav
		filled += 1

	if not filled:
		frappe.throw(
			_("The file has no NAV dated {0} for any security of type {1}").format(
				frappe.bold(formatdate(doc.price_date)), frappe.bold(doc.loan_security_type)
			)
		)

	# A row left without a price would block the save. Dropped, it counts as missing instead
	doc.set("items", [row for row in doc.items if flt(row.price) > 0])
	doc.save()
	attach_file(file, doc)
	return {"name": doc.name, "filled": filled}


def validate_price_update(doc):
	if doc.doctype != "Loan Security Price Update":
		frappe.throw(_("Only a Loan Security Price Update can read a NAV file"))
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft Loan Security Price Update can read a NAV file"))
	if not doc.price_date:
		frappe.throw(_("Set the Price Date before you read a NAV file"))
	if not (
		doc.loan_security_type
		and frappe.db.get_value("Loan Security Type", doc.loan_security_type, "is_mutual_fund")
	):
		frappe.throw(
			_("Loan Security Type {0} is not a mutual fund").format(frappe.bold(doc.loan_security_type or ""))
		)


def get_securities_to_price(doc, rows):
	"""The pledged securities of the type, as Get Securities lists them, and any row already on the form."""
	names = doc.get_pledged_securities() | set(rows)
	if not names:
		return []
	return frappe.get_all(
		"Loan Security",
		filters={
			"name": ("in", list(names)),
			"loan_security_type": doc.loan_security_type,
			"disabled": 0,
			"amfi_scheme_code": ("is", "set"),
		},
		fields=["name", "amfi_scheme_code"],
		order_by="name",
	)


def attach_file(file, doc):
	# Keep the file as the source of these prices. An update read before its first save had no name to attach to
	if file.attached_to_name or file.owner != frappe.session.user:
		return
	file.attached_to_doctype = doc.doctype
	file.attached_to_name = doc.name
	file.save()


def parse_nav_file(content, price_date):
	"""Map each scheme code to its NAV on price_date.

	A scheme line is `Scheme Code;ISIN;ISIN;Scheme Name;...;NAV;Date`. Fund house and category
	headings have no semicolons and are skipped.
	"""
	if isinstance(content, bytes):
		content = content.decode("utf-8", errors="replace")

	navs = {}
	for line in content.splitlines():
		fields = [field.strip() for field in line.split(";")]
		if len(fields) < 6 or not fields[0].isdigit():
			continue
		try:
			nav_date = datetime.strptime(fields[-1], "%d-%b-%Y").date()
		except ValueError:
			continue
		nav = flt(fields[-2])
		if nav_date == price_date and nav > 0:
			navs[fields[0]] = nav
	return navs
