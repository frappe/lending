# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from lending.loan_integrations import log
from lending.loan_integrations.adapters import get_adapter
from lending.loan_integrations.base import BaseAdapter, Refused

SETTINGS = "Lending Settings"
REGISTRY = "Mutual Fund Registry"
NAV = "Mutual Fund NAV"
REGISTRY_FIELD = "mutual_fund_registry_adapter"
NAV_FIELD = "mutual_fund_nav_adapter"
STATEMENT_OF_ACCOUNT = "Statement of Account"


class RegistryAdapter(BaseAdapter):
	"""Holdings and liens on mutual fund folios, such as MFCentral for CAMS and KFintech folios."""

	provider_type = REGISTRY

	def send_otp(self, context: dict) -> dict:
		"""Ask the investor for consent to read their folios. Returns `request_id`."""
		raise NotImplementedError

	def fetch_holdings(self, context: dict) -> dict:
		"""Returns `holdings`: amfi_scheme_code, scheme_name, folio_number, units, free_units,
		holding_mode, holding_type and `lots` of purchase_date and units."""
		raise NotImplementedError

	def mark_lien(self, context: dict) -> dict:
		"""Ask the investor to approve a lien on `lines`. Returns `request_id`."""
		raise NotImplementedError

	def confirm_lien(self, context: dict) -> dict:
		"""Returns `liens`: the `row` of each line and its lien_reference."""
		raise NotImplementedError

	def revoke_lien(self, context: dict) -> dict:
		"""Returns `releases`: the `row` of each released line and its release_reference."""
		raise NotImplementedError

	def invoke_lien(self, context: dict) -> dict:
		"""Redeem the pledged `items`. Returns `redemption_reference` and `items`:
		loan_security, units, nav, exit_load and stt."""
		raise NotImplementedError


class NavAdapter(BaseAdapter):
	"""The daily NAV of every scheme, in the format of AMFI's NAVAll.txt."""

	provider_type = NAV

	def fetch_nav_file(self, context: dict) -> dict:
		"""Returns `content`, the text of the file."""
		raise NotImplementedError


def get_adapter_key(fieldname):
	return frappe.db.get_single_value(SETTINGS, fieldname)


def call(fieldname, operation, context, doc, refuse=False):
	"""Log every call as an Integration Request, then return the adapter's answer.

	Unlike run_integration, a second call asks again: an expired OTP is sent again, and a holdings
	fetch shows the folios as they are now. The document's own state stops a repeated lien.
	A failure is shown to staff and returns None; with `refuse`, the portal gets Refused instead.
	"""
	key = get_adapter_key(fieldname)
	if not key:
		frappe.throw(_("Set the {0} in Lending Settings first").format(_(frappe.get_meta(SETTINGS).get_label(fieldname))))

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
	except Exception as e:
		log.fail(request, e)
		if refuse:
			raise Refused(str(e)) from e
		# Shown rather than raised, so the request and its error stay logged
		frappe.msgprint(str(e), title=_("{0} did not answer").format(key), indicator="red")
		return None

	log.succeed(request, output)
	return output


def is_lien_line(row):
	return row.is_mutual_fund and row.holding_mode == STATEMENT_OF_ACCOUNT


def uses_registry():
	return bool(get_adapter_key(REGISTRY_FIELD))


@frappe.whitelist(methods=["GET"])
def adapter_choices():
	frappe.has_permission(SETTINGS, "read", throw=True)

	from lending.loan_integrations.adapters import adapter_keys

	return {REGISTRY_FIELD: adapter_keys(REGISTRY), NAV_FIELD: adapter_keys(NAV)}


@frappe.whitelist(methods=["GET"])
def get_setup():
	return {"registry": uses_registry(), "nav": bool(get_adapter_key(NAV_FIELD))}


def get_doc_for(doctype, name, perm="write"):
	doc = frappe.get_doc(doctype, name)
	doc.check_permission(perm)
	return doc


def get_applicant_contact(doc):
	if doc.applicant_type != "Customer":
		return {}
	customer = frappe.db.get_value(
		"Customer", doc.applicant, ["tax_id", "mobile_no", "customer_name"], as_dict=True
	) or {}
	return {"pan": customer.get("tax_id"), "mobile": customer.get("mobile_no"), "name": customer.get("customer_name")}


# Holdings


@frappe.whitelist(methods=["POST"])
def send_holdings_otp(loan_security_assignment: str, pan: str, mobile: str):
	doc = get_doc_for("Loan Security Assignment", loan_security_assignment)
	output = call(REGISTRY_FIELD, "send_otp", {"pan": pan.strip().upper(), "mobile": mobile}, doc)
	return output and {"request_id": output.get("request_id")}


@frappe.whitelist(methods=["POST"])
def fetch_holdings(loan_security_assignment: str, pan: str, request_id: str, otp: str):
	doc = get_doc_for("Loan Security Assignment", loan_security_assignment)
	output = call(
		REGISTRY_FIELD,
		"fetch_holdings",
		{"pan": pan.strip().upper(), "request_id": request_id, "otp": otp},
		doc,
	)
	if output is None:
		return None
	return match_holdings(output.get("holdings") or [])


def match_holdings(holdings):
	codes = [str(holding.get("amfi_scheme_code")) for holding in holdings]
	securities = {
		row.amfi_scheme_code: row
		for row in frappe.get_all(
			"Loan Security",
			filters={"amfi_scheme_code": ("in", codes), "disabled": 0, "is_mutual_fund": 1},
			fields=["name", "amfi_scheme_code", "lock_in_days"],
		)
	}
	for holding in holdings:
		security = securities.get(str(holding.get("amfi_scheme_code")))
		holding["loan_security"] = security.name if security else None
		holding["lock_in_days"] = security.lock_in_days if security else 0
	return holdings


@frappe.whitelist(methods=["POST"])
def add_holdings(loan_security_assignment: str, lines: str | list):
	doc = get_doc_for("Loan Security Assignment", loan_security_assignment)
	lines = frappe.parse_json(lines)

	if doc.docstatus == 0:
		for line in lines:
			doc.append("securities", get_pledge_line(doc, line))
	elif doc.status == "Pledge Requested":
		fill_requested_lines(doc, lines)
	else:
		frappe.throw(_("Holdings can be added only to a draft or a Pledge Requested assignment"))

	doc.save()
	return doc.name


def save_holding(applicant_type, applicant, line):
	key = {
		"applicant_type": applicant_type,
		"applicant": applicant,
		"loan_security": line["loan_security"],
		"folio_number": line["folio_number"],
	}
	name = frappe.db.get_value("Mutual Fund Holding", key)
	holding = frappe.get_doc("Mutual Fund Holding", name) if name else frappe.new_doc("Mutual Fund Holding")
	holding.update(key)
	holding.update(
		{
			"holding_mode": line.get("holding_mode"),
			"holding_type": line.get("holding_type"),
			"units_held": flt(line.get("units")) or holding.units_held,
		}
	)
	if line.get("lots"):
		holding.lots = []
		for lot in line["lots"]:
			holding.append("lots", {"purchase_date": lot["purchase_date"], "units": flt(lot["units"])})
		holding.fetched_on = now_datetime()
	holding.save(ignore_permissions=True)
	return holding.name


def get_pledge_line(doc, line):
	return {
		"loan_security": line["loan_security"],
		"qty": flt(line["qty"]),
		"mutual_fund_holding": save_holding(doc.applicant_type, doc.applicant, line),
		"purchase_date": line.get("purchase_date"),
	}


def fill_requested_lines(doc, lines):
	# The application fixed the securities and units, so only the fund details are filled in
	by_security = {}
	for line in lines:
		by_security.setdefault(line["loan_security"], line)
	for row in doc.securities:
		line = by_security.get(row.loan_security)
		if not line:
			continue
		row.mutual_fund_holding = save_holding(doc.applicant_type, doc.applicant, line)
		row.purchase_date = line.get("purchase_date")


# Lien


@frappe.whitelist(methods=["POST"])
def request_lien(loan_security_assignment: str):
	return send_lien_otp(get_doc_for("Loan Security Assignment", loan_security_assignment))


def send_lien_otp(doc, refuse=False):
	if doc.lien_status == "Marked":
		frappe.throw(_("The lien on {0} is already marked").format(doc.name))
	if doc.docstatus == 1 and doc.status != "Pledge Requested":
		frappe.throw(_("A lien can be requested only before the units are pledged"))

	lines = get_lien_lines(doc)
	if not lines:
		frappe.throw(_("No line holds mutual fund units as a Statement of Account"))
	for line in lines:
		if not line["folio_number"]:
			frappe.throw(_("Row {0}: Enter the Folio Number before you request the lien").format(line["idx"]))

	context = {**get_applicant_contact(doc), "lines": lines}
	output = call(REGISTRY_FIELD, "mark_lien", context, doc, refuse=refuse)
	if output is None:
		return None

	doc.db_set({"lien_status": "OTP Sent", "lien_request_id": output.get("request_id")})
	return doc.lien_status


@frappe.whitelist(methods=["POST"])
def confirm_lien(loan_security_assignment: str, otp: str):
	return apply_lien_otp(get_doc_for("Loan Security Assignment", loan_security_assignment), otp)


def apply_lien_otp(doc, otp, refuse=False):
	if doc.lien_status != "OTP Sent":
		frappe.throw(_("Request the lien before you confirm it"))

	context = {"request_id": doc.lien_request_id, "otp": otp, "lines": get_lien_lines(doc)}
	output = call(REGISTRY_FIELD, "confirm_lien", context, doc, refuse=refuse)
	if output is None:
		return None

	references = {lien["row"]: lien["lien_reference"] for lien in output.get("liens") or []}
	for row in doc.securities:
		if row.name in references:
			row.db_set("lien_reference", references[row.name])
	doc.db_set("lien_status", "Marked")
	return doc.lien_status


def get_lien_lines(doc):
	return [
		{
			"row": row.name,
			"idx": row.idx,
			"amfi_scheme_code": frappe.db.get_value("Loan Security", row.loan_security, "amfi_scheme_code"),
			"folio_number": row.folio_number,
			"units": row.qty,
		}
		for row in doc.securities
		if is_lien_line(row)
	]


def validate_lien_marked(doc, title=None):
	if not uses_registry() or doc.lien_status == "Marked":
		return
	if any(is_lien_line(row) for row in doc.securities):
		frappe.throw(
			_("Mark the lien on the mutual fund units of {0} before they are pledged").format(
				frappe.bold(doc.name)
			),
			title=title or _("Lien Not Marked"),
		)


# Release


@frappe.whitelist(methods=["POST"])
def revoke_lien(loan_security_release: str):
	doc = get_doc_for("Loan Security Release", loan_security_release)
	if doc.docstatus != 1 or doc.status != "Requested":
		frappe.throw(_("A lien can be revoked only on a submitted, Requested release"))

	rows = [
		row
		for row in get_mutual_fund_rows(doc.securities)
		if not row.release_reference and is_statement_holding(doc.loan, row.loan_security)
	]
	if not rows:
		frappe.throw(_("No mutual fund line waits for its lien to be revoked"))

	context = {
		"loan": doc.loan,
		"lines": [
			{
				"row": row.name,
				"amfi_scheme_code": row.amfi_scheme_code,
				"units": row.qty,
				"lien_references": get_lien_references(doc.loan, row.loan_security),
			}
			for row in rows
		],
	}
	output = call(REGISTRY_FIELD, "revoke_lien", context, doc)
	if output is None:
		return None

	references = {release["row"]: release["release_reference"] for release in output.get("releases") or []}
	for row in doc.securities:
		if row.name in references:
			row.db_set("release_reference", references[row.name])
	return len(references)


def validate_lien_revoked(doc):
	if not uses_registry():
		return
	for row in get_mutual_fund_rows(doc.securities):
		if is_statement_holding(doc.loan, row.loan_security) and not row.release_reference:
			frappe.throw(
				_("Row {0}: Revoke the lien on Loan Security {1} before the release is approved").format(
					row.idx, frappe.bold(row.loan_security)
				),
				title=_("Lien Not Revoked"),
			)


def get_mutual_fund_rows(rows):
	codes = dict(
		frappe.get_all(
			"Loan Security",
			filters={"name": ("in", [row.loan_security for row in rows]), "is_mutual_fund": 1},
			fields=["name", "amfi_scheme_code"],
			as_list=1,
		)
	)
	result = []
	for row in rows:
		if row.loan_security in codes:
			row.amfi_scheme_code = codes[row.loan_security]
			result.append(row)
	return result


def get_pledged_lines(loan, loan_security):
	return frappe.get_all(
		"Pledge",
		filters={
			"parenttype": "Loan Security Assignment",
			"parent": ("in", frappe.get_all("Loan Security Assignment", {"loan": loan, "docstatus": 1, "status": "Pledged"}, pluck="name")),
			"loan_security": loan_security,
		},
		fields=["folio_number", "holding_mode", "lien_reference", "qty"],
	)


def get_lien_references(loan, loan_security):
	return [line.lien_reference for line in get_pledged_lines(loan, loan_security) if line.lien_reference]


def is_statement_holding(loan, loan_security):
	return any(line.holding_mode == STATEMENT_OF_ACCOUNT for line in get_pledged_lines(loan, loan_security))


# Sale


@frappe.whitelist(methods=["POST"])
def request_redemption(loan_security_sale: str):
	doc = get_doc_for("Loan Security Sale", loan_security_sale)
	if doc.docstatus != 0:
		frappe.throw(_("A redemption can be requested only on a draft sale"))
	if doc.redemption_reference:
		frappe.throw(_("The redemption of {0} is already requested").format(doc.name))

	rows = [
		row
		for row in get_mutual_fund_rows(doc.items)
		if flt(row.qty) > 0 and is_statement_holding(doc.loan, row.loan_security)
	]
	if not rows:
		frappe.throw(_("No item of this sale is a Statement of Account mutual fund with units to sell"))

	context = {
		"loan": doc.loan,
		"items": [
			{
				"loan_security": row.loan_security,
				"amfi_scheme_code": row.amfi_scheme_code,
				"units": row.qty,
				"lien_references": get_lien_references(doc.loan, row.loan_security),
			}
			for row in rows
		],
	}
	output = call(REGISTRY_FIELD, "invoke_lien", context, doc)
	if output is None:
		return None

	redeemed = {item["loan_security"]: item for item in output.get("items") or []}
	deductions = 0
	for row in doc.items:
		item = redeemed.get(row.loan_security)
		if not item:
			continue
		row.sold_qty = flt(item["units"])
		row.sale_price = flt(item["nav"])
		deductions += flt(item.get("exit_load")) + flt(item.get("stt"))

	doc.deductions = flt(doc.deductions) + deductions
	doc.redemption_reference = output.get("redemption_reference")
	doc.save()
	return doc.redemption_reference


def validate_redemption(doc):
	if not uses_registry() or doc.redemption_reference:
		return
	for row in get_mutual_fund_rows(doc.items):
		if flt(row.sold_qty) and is_statement_holding(doc.loan, row.loan_security):
			frappe.throw(
				_("Request the redemption of the mutual fund units before the sale is submitted"),
				title=_("Redemption Not Requested"),
			)
