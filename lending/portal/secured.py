# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import add_days, add_months, cint, flt, getdate, now_datetime, nowdate
from frappe.utils.file_manager import save_file
from frappe.utils.pdf import get_pdf

from lending.collateral.mutual_fund import registry
from lending.loan_integrations import verification
from lending.loan_integrations.base import Refused
from lending.loan_management.doctype.loan.loan import new_loan_disbursement
from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan,
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)
from lending.portal import login
from lending.portal.accounts import create_customer, link_portal_user
from lending.portal.apply import mask, spend_token, verified_mobile, with_country_code
from lending.portal.core import (
	STATUS_LABELS,
	application_url,
	as_administrator,
	assert_public_apply_enabled,
	brand_payload,
	clean,
	get_loans,
	get_portal_customers,
	loan_url,
	long_date,
	money,
	shell_payload,
)
from lending.portal.downloads import render
from lending.portal.loans import (
	DRAWABLE_STATUSES,
	check_drawdown,
	drawable_amount,
	next_due_date,
	pending_disbursement,
)
from lending.portal.print_formats import SANCTION_FORMAT

ROUTE = "/borrower-portal/secured-loan"

# No registration step: the borrower signed up or logged in before reaching the journey.
STEPS = (
	("pan", "Verify PAN"),
	("eligibility", "Check eligibility"),
	("vault", "Choose funds"),
	("kyc", "KYC"),
	("pledge", "Pledge funds"),
	("bank", "Bank details"),
	("esign", "E-sign"),
	("loan", "Your loan"),
)

MUTUAL_FUNDS = "Mutual Funds"
# Collaterals whose journey is built; the others are listed as coming soon.
JOURNEYS = (MUTUAL_FUNDS,)
COLLATERALS = (
	(MUTUAL_FUNDS, "Loan against mutual funds"),
	("Shares", "Loan against shares"),
	("Gold", "Gold loan"),
	("Vehicle", "Vehicle loan"),
)

AUTOMATIC = "Automatic"
PAN_LENGTH = 10
ESIGN_PREFIX = "portal-apply-esign"
ESIGN_TTL = 15 * 60
LETTER_URL = "/api/method/lending.portal.secured.download_sanction_letter"


# Who and where


def borrower() -> str:
	customers = get_portal_customers()
	if not customers:
		frappe.throw(_("Your login is not linked to a borrower yet. Please contact us."), frappe.PermissionError)

	return customers[0]


def kyc_record(customer: str, create: bool = False):
	if frappe.db.exists("Borrower KYC", customer):
		return frappe.get_doc("Borrower KYC", customer)

	doc = frappe.new_doc("Borrower KYC")
	doc.customer = customer
	if create:
		doc.insert(ignore_permissions=True)

	return doc


def secured_product(collateral: str) -> str | None:
	return frappe.db.get_value(
		"Portal Secured Loan",
		{"parent": "Lending Settings", "parenttype": "Lending Settings", "collateral": collateral},
		"loan_product",
	)


def journey_application(customer: str) -> str | None:
	return frappe.db.get_value(
		"Loan Application",
		{
			"applicant_type": "Customer",
			"applicant": customer,
			"portal_collateral": ("is", "set"),
			"docstatus": ("<", 2),
			"status": ("!=", "Rejected"),
		},
		"name",
		order_by="creation desc",
	)


def open_application(customer: str) -> str | None:
	name = journey_application(customer)
	if name and not loan_for(name):
		return name


def loan_for(application: str) -> str | None:
	return frappe.db.get_value("Loan", {"loan_application": application, "docstatus": 1}, "name")


def assignment_for(application: str) -> str | None:
	return frappe.db.get_value(
		"Loan Security Assignment", {"loan_application": application, "docstatus": 1}, "name"
	)


def own_application(customer: str):
	name = open_application(customer)
	if not name:
		frappe.throw(_("Please choose the units to pledge first."), frappe.ValidationError)

	return frappe.get_doc("Loan Application", name)


def refused(error: Refused) -> dict:
	return {"ok": False, "message": str(error)}


# The page


@frappe.whitelist()
def get_secured_loan() -> dict:
	customer = borrower()
	payload = shell_payload(_("Loan against securities"), "", get_loans([customer]))
	kyc = kyc_record(customer)
	application = journey_application(customer)
	holdings = holding_rows(customer)

	payload.update(
		{
			"breadcrumbs": [{"label": _("Loan against securities"), "route": ""}],
			"customer_name": frappe.db.get_value("Customer", customer, "customer_name"),
			"mobile": mask(customer_mobile(customer)),
			"pan": pan_payload(kyc),
			"collaterals": collateral_options(),
			"holdings": holdings,
			"totals": holding_totals(holdings),
			"product": product_payload(application),
			"application": application_payload(application),
			"kyc": kyc_payload(kyc),
			"pledge": pledge_payload(application),
			"bank": bank_payload(application),
			"esign": esign_payload(application),
			"loan": loan_payload(application),
			"approval": frappe.db.get_single_value("Lending Settings", "portal_loan_approval") or AUTOMATIC,
			"currency": frappe.defaults.get_global_default("currency") or "INR",
		}
	)
	payload["steps"] = step_rows(payload)
	payload["current"] = next((row["key"] for row in payload["steps"] if row["state"] == "now"), "loan")

	return payload


def step_rows(payload: dict) -> list[dict]:
	application = payload["application"]
	done = {
		"pan": payload["pan"]["verified"],
		"eligibility": bool(payload["holdings"]),
		"vault": bool(application.get("name")),
		"kyc": payload["kyc"]["verified"],
		"pledge": payload["pledge"]["marked"],
		"bank": bool(payload["bank"].get("account")),
		"esign": bool(payload["esign"].get("signed_on")),
		"loan": bool(payload["loan"].get("name")),
	}

	rows = []
	reached = True
	for key, label in STEPS:
		state = "done" if done[key] and reached else ("now" if reached else "todo")
		reached = reached and done[key]
		rows.append({"key": key, "label": _(label), "state": state})

	return rows


def customer_mobile(customer: str) -> str:
	record = frappe.db.get_value("Customer", customer, ["mobile_no"], as_dict=True)
	mobile = record.mobile_no or frappe.db.get_value("User", frappe.session.user, "mobile_no") or ""

	return with_country_code(mobile) if mobile else ""


def pan_payload(kyc) -> dict:
	return {
		"verified": bool(kyc.pan_verified_on),
		"pan": masked_pan(kyc.pan),
		"name": kyc.name_on_pan or "",
		"verified_on": long_date(kyc.pan_verified_on),
	}


def masked_pan(pan: str | None) -> str:
	return f"{pan[:2]}{'•' * 5}{pan[-3:]}" if pan else ""


def collateral_options() -> list[dict]:
	options = []
	for collateral, label in COLLATERALS:
		available = collateral in JOURNEYS and bool(secured_product(collateral))
		options.append(
			{
				"value": collateral,
				"label": _(label) if available else _("{0} (coming soon)").format(_(label)),
				"available": available,
			}
		)

	return options


def kyc_payload(kyc) -> dict:
	return {
		"verified": kyc.kyc_status == "Verified",
		"status": kyc.kyc_status or "",
		"name": kyc.name_as_per_kyc or "",
		"verified_on": long_date(kyc.kyc_verified_on),
	}


# Holdings


def holding_rows(customer: str) -> list[dict]:
	holdings = frappe.get_all(
		"Mutual Fund Holding",
		filters={"applicant_type": "Customer", "applicant": customer},
		fields=["name", "loan_security", "folio_number", "units_held", "lock_in_days", "fetched_on"],
		order_by="loan_security",
	)

	return [holding_row(holding) for holding in holdings]


def holding_row(holding) -> dict:
	from lending.collateral.doctype.mutual_fund_holding.mutual_fund_holding import get_pledged_units

	security = frappe.db.get_value(
		"Loan Security", holding.loan_security, ["loan_security_name", "haircut"], as_dict=True
	)
	nav = flt(get_loan_security_price(holding.loan_security))
	pledged = flt(get_pledged_units(holding.name))
	free = max(flt(holding.units_held) - pledged, 0)
	# Earlier pledges took unlocked units too, oldest first, as lot_lines does.
	pledgeable = max(unlocked_units(holding) - pledged, 0)
	value = flt(holding.units_held) * nav
	eligible = eligible_amount(pledgeable, nav, security.haircut)

	return {
		"holding": holding.name,
		"scheme": security.loan_security_name or holding.loan_security,
		"folio": holding.folio_number,
		"units": number(holding.units_held),
		"pledged_units": flt(pledged, 3),
		"pledgeable_units": flt(pledgeable, 3),
		"nav": nav,
		"nav_label": money(nav),
		"value": value,
		"value_label": money(value),
		"haircut": flt(security.haircut),
		"haircut_label": _("{0}% haircut").format(number(security.haircut)),
		"eligible": eligible,
		"eligible_label": money(eligible),
		"note": lock_note(holding, pledgeable, free),
	}


def unlocked_units(holding) -> float:
	lots = frappe.get_all(
		"Mutual Fund Holding Lot",
		filters={"parent": holding.name, "parenttype": "Mutual Fund Holding"},
		fields=["purchase_date", "units"],
	)
	if not lots or not holding.lock_in_days:
		return flt(holding.units_held)

	return sum(flt(lot.units) for lot in lots if unlocks_on(lot.purchase_date, holding.lock_in_days) <= getdate())


def unlocks_on(purchase_date, lock_in_days):
	return getdate(add_days(purchase_date, cint(lock_in_days)))


def lock_note(holding, pledgeable: float, free: float) -> str:
	if not free:
		return _("All units are pledged")
	if pledgeable < free:
		return _("{0} units are still in lock-in").format(number(free - pledgeable))

	return ""


def number(value) -> str:
	return f"{flt(value, 3):g}"


def eligible_amount(units: float, nav: float, haircut: float) -> float:
	return flt(units * nav * (1 - flt(haircut) / 100), 2)


def holding_totals(holdings: list[dict]) -> dict:
	value = sum(row["value"] for row in holdings)
	eligible = sum(row["eligible"] for row in holdings)

	return {"value": money(value), "eligible": money(eligible), "eligible_amount": eligible}


# Step 1: Verify PAN


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def verify_pan() -> dict:
	customer = borrower()
	pan = clean(frappe.form_dict.get("pan")).upper()
	if len(pan) != PAN_LENGTH:
		frappe.throw(_("A PAN has 10 characters, like ABCDE1234F."), frappe.ValidationError)

	kyc = kyc_record(customer, create=True)
	if kyc.pan_verified_on and kyc.pan != pan:
		frappe.throw(_("Your PAN is already verified. Please contact us to change it."), frappe.ValidationError)

	# The registry and the bureau read the PAN from the Customer, so the two must agree.
	name, tax_id = frappe.db.get_value("Customer", customer, ["customer_name", "tax_id"])
	if tax_id and tax_id.upper() != pan:
		frappe.throw(_("This PAN does not match our records. Please contact us."), frappe.ValidationError)

	try:
		output = verification.call(verification.PAN, "verify_pan", {"pan": pan, "name": name}, kyc)
	except Refused as e:
		return refused(e)

	if not output.get("verified"):
		return {"ok": False, "message": _("This PAN could not be verified.")}

	kyc.update(
		{
			"pan": pan,
			"name_on_pan": output.get("name_on_pan"),
			"pan_reference": output.get("reference"),
			"pan_verified_on": now_datetime(),
		}
	)
	kyc.save(ignore_permissions=True)

	if not tax_id:
		frappe.db.set_value("Customer", customer, "tax_id", pan)

	return {"ok": True}


# Step 2: Check eligibility


def verified_kyc(customer: str):
	kyc = kyc_record(customer)
	if not kyc.pan_verified_on:
		frappe.throw(_("Please verify your PAN first."), frappe.ValidationError)

	return kyc


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def send_holdings_otp() -> dict:
	customer = borrower()
	read_collateral()
	kyc = verified_kyc(customer)
	mobile = customer_mobile(customer)

	try:
		output = registry.call(
			registry.REGISTRY_FIELD, "send_otp", {"pan": kyc.pan, "mobile": mobile}, kyc, refuse=True
		)
	except Refused as e:
		return refused(e)

	return {
		"ok": True,
		"request_id": output.get("request_id"),
		"message": _("We sent an OTP to the mobile number ending {0}, registered with your funds.").format(
			mobile[-4:]
		),
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def fetch_holdings() -> dict:
	customer = borrower()
	read_collateral()
	kyc = verified_kyc(customer)
	context = {
		"pan": kyc.pan,
		"request_id": clean(frappe.form_dict.get("request_id")),
		"otp": clean(frappe.form_dict.get("otp")),
	}

	try:
		output = registry.call(registry.REGISTRY_FIELD, "fetch_holdings", context, kyc, refuse=True)
	except Refused as e:
		return refused(e)

	holdings = registry.match_holdings(output.get("holdings") or [])
	approved = [holding for holding in holdings if holding.get("loan_security")]
	for holding in approved:
		registry.save_holding("Customer", customer, holding)

	return {
		"ok": True,
		"approved": len(approved),
		"not_approved": [
			{"scheme": holding.get("scheme_name"), "folio": holding.get("folio_number")}
			for holding in holdings
			if not holding.get("loan_security")
		],
	}


def read_collateral() -> str:
	collateral = clean(frappe.form_dict.get("collateral")) or MUTUAL_FUNDS
	if collateral not in JOURNEYS or not secured_product(collateral):
		frappe.throw(_("{0} cannot be applied for online yet.").format(_(collateral)), frappe.ValidationError)

	return collateral


# Step 3: Choose funds


def product_payload(application: str | None) -> dict:
	name = (
		frappe.db.get_value("Loan Application", application, "loan_product") if application else None
	) or secured_product(MUTUAL_FUNDS)
	if not name:
		return {}

	product = frappe.db.get_value(
		"Loan Product",
		name,
		["name", "product_name", "rate_of_interest", "maximum_loan_amount", "is_term_loan"],
		as_dict=True,
	)

	return {
		"name": product.name,
		"label": product.product_name or product.name,
		"rate": _("{0}% a year").format(flt(product.rate_of_interest)),
		"maximum": flt(product.maximum_loan_amount),
		"maximum_label": money(product.maximum_loan_amount) if product.maximum_loan_amount else "",
		"asks_tenure": bool(product.is_term_loan),
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=60 * 60)
def start_application() -> dict:
	customer = borrower()
	verified_kyc(customer)
	collateral = read_collateral()
	product = frappe.get_doc("Loan Product", secured_product(collateral))
	pledges = proposed_pledges(customer, frappe.parse_json(frappe.form_dict.get("lines") or "[]"))
	amount = flt(frappe.form_dict.get("loan_amount"))
	tenure = cint(frappe.form_dict.get("tenure"))

	if amount <= 0:
		frappe.throw(_("Please enter the amount you need."), frappe.ValidationError)
	if product.is_term_loan and tenure <= 0:
		frappe.throw(_("Please choose over how many months to repay."), frappe.ValidationError)

	name = open_application(customer)
	application = frappe.get_doc("Loan Application", name) if name else frappe.new_doc("Loan Application")
	if application.docstatus:
		frappe.throw(_("Your application is already sent, so its units cannot change."), frappe.ValidationError)

	contact = frappe.db.get_value("User", frappe.session.user, ["email", "full_name"], as_dict=True)
	application.update(
		{
			"applicant_type": "Customer",
			"applicant": customer,
			"applicant_name": frappe.db.get_value("Customer", customer, "customer_name"),
			"applicant_email_address": contact.email,
			"applicant_phone_number": customer_mobile(customer),
			"company": product.company,
			"posting_date": nowdate(),
			"loan_product": product.name,
			"is_secured_loan": 1,
			"is_term_loan": product.is_term_loan,
			"rate_of_interest": product.rate_of_interest,
			"loan_amount": amount,
			"portal_collateral": collateral,
			"repayment_method": "Repay Over Number of Periods" if product.is_term_loan else None,
			"repayment_periods": tenure if product.is_term_loan else None,
		}
	)
	application.proposed_pledges = []
	for pledge in pledges:
		application.append("proposed_pledges", pledge)

	# Loan Application grants create to staff roles only; ownership is checked above.
	application.save(ignore_permissions=True)

	return {"ok": True, "application": application.name}


def proposed_pledges(customer: str, lines: list) -> list[dict]:
	# Summed per holding, so splitting one holding over lines cannot pass the limit twice.
	wanted = {}
	for line in lines:
		units = flt(line.get("units"))
		if units > 0:
			wanted[line.get("holding")] = wanted.get(line.get("holding"), 0) + units

	pledges = []
	for name, units in wanted.items():
		holding = frappe.db.get_value(
			"Mutual Fund Holding",
			name,
			["name", "applicant_type", "applicant", "loan_security", "lock_in_days"],
			as_dict=True,
		)
		if not holding or (holding.applicant_type, holding.applicant) != ("Customer", customer):
			raise frappe.PermissionError(_("Not permitted"))

		row = holding_row(frappe._dict(holding, **holding_fields(holding.name)))
		if units > row["pledgeable_units"] + 0.0001:
			frappe.throw(
				_("You can pledge up to {0} units of {1}.").format(row["pledgeable_units"], row["scheme"]),
				frappe.ValidationError,
			)

		pledges.extend(lot_lines(holding, units, row["pledged_units"]))

	if not pledges:
		frappe.throw(_("Please choose the units to pledge."), frappe.ValidationError)

	return pledges


def holding_fields(holding: str) -> dict:
	return frappe.db.get_value(
		"Mutual Fund Holding", holding, ["folio_number", "units_held", "fetched_on"], as_dict=True
	)


def lot_lines(holding, units: float, pledged: float) -> list[dict]:
	lots = frappe.get_all(
		"Mutual Fund Holding Lot",
		filters={"parent": holding.name, "parenttype": "Mutual Fund Holding"},
		fields=["purchase_date", "units"],
		order_by="purchase_date",
	)
	if not lots:
		return [line_for(holding, units)]

	lines = []
	for lot in lots:
		if units <= 0:
			break
		if holding.lock_in_days and unlocks_on(lot.purchase_date, holding.lock_in_days) > getdate():
			continue

		# Skip what earlier pledges already took from the oldest lots.
		skipped = min(flt(lot.units), pledged)
		pledged -= skipped
		take = min(flt(lot.units) - skipped, units)
		if take > 0:
			lines.append(line_for(holding, take, lot.purchase_date))
			units -= take

	if units > 0.0001:
		# Units the registry sent no lot for; their lock-in is unknown, so only a fund without one takes them.
		if holding.lock_in_days:
			frappe.throw(
				_("Some units of {0} cannot be pledged yet. Please choose fewer.").format(holding.loan_security),
				frappe.ValidationError,
			)
		lines.append(line_for(holding, units))

	return lines


def line_for(holding, units: float, purchase_date=None) -> dict:
	return {
		"loan_security": holding.loan_security,
		"qty": units,
		"haircut": frappe.db.get_value("Loan Security", holding.loan_security, "haircut"),
		"mutual_fund_holding": holding.name,
		"purchase_date": purchase_date,
	}


def application_payload(application: str | None) -> dict:
	if not application:
		return {}

	doc = frappe.get_doc("Loan Application", application)
	pledges = [
		{
			"key": row.name,
			"scheme": row.loan_security_name or row.loan_security,
			"folio": frappe.db.get_value("Mutual Fund Holding", row.mutual_fund_holding, "folio_number") or "",
			"units": number(row.qty),
			"value": money(row.amount),
			"eligible": money(row.post_haircut_amount),
		}
		for row in doc.proposed_pledges
	]

	return {
		"name": doc.name,
		"url": application_url(doc.name),
		"loan_amount": money(doc.loan_amount),
		"amount": flt(doc.loan_amount),
		"tenure": cint(doc.repayment_periods),
		"tenure_label": _("{0} months").format(doc.repayment_periods) if doc.repayment_periods else "",
		"maximum": money(doc.maximum_loan_amount),
		"value": money(sum(flt(row.amount) for row in doc.proposed_pledges)),
		"emi": money(doc.repayment_amount) if doc.repayment_amount else "",
		"pledges": pledges,
		"sent": doc.docstatus == 1,
		"lines": [
			{"holding": row.mutual_fund_holding, "units": flt(row.qty)} for row in doc.proposed_pledges
		],
	}


# Step 4: KYC


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def start_kyc() -> dict:
	customer = borrower()
	own_application(customer)
	kyc = verified_kyc(customer)
	context = {
		"name": frappe.db.get_value("Customer", customer, "customer_name"),
		"mobile": customer_mobile(customer),
		"return_url": f"{ROUTE}?step=kyc",
	}

	try:
		output = verification.call(verification.KYC, "start", context, kyc)
	except Refused as e:
		return refused(e)

	kyc.update({"kyc_status": "Pending", "kyc_request_id": output.get("request_id")})
	kyc.save(ignore_permissions=True)

	return {"ok": True, "redirect_url": output.get("redirect_url")}


@frappe.whitelist(methods=["POST"])
def complete_kyc() -> dict:
	customer = borrower()
	kyc = kyc_record(customer)
	if kyc.kyc_status == "Verified":
		return {"ok": True}
	if not kyc.kyc_request_id:
		frappe.throw(_("Please start your KYC first."), frappe.ValidationError)

	try:
		output = verification.call(verification.KYC, "fetch", {"request_id": kyc.kyc_request_id}, kyc)
	except Refused as e:
		return refused(e)

	status = output.get("status")
	if status == "Pending":
		return {"ok": False, "message": _("Your KYC is not finished yet. Please complete it on DigiLocker.")}

	kyc.kyc_status = status
	if status == "Verified":
		kyc.update(
			{
				"kyc_reference": output.get("reference"),
				"kyc_verified_on": now_datetime(),
				"name_as_per_kyc": output.get("name"),
				"date_of_birth": output.get("date_of_birth"),
				"kyc_address": output.get("address"),
			}
		)
	kyc.save(ignore_permissions=True)

	if status != "Verified":
		return {"ok": False, "message": _("Your KYC could not be completed. Please try again.")}

	return {"ok": True}


@frappe.whitelist()
def get_kyc_consent() -> dict:
	customer = borrower()
	assert_sample_kyc(customer)

	return {
		**brand_payload(),
		"customer_name": frappe.db.get_value("Customer", customer, "customer_name"),
		"documents": [_("Aadhaar card"), _("PAN card")],
	}


@frappe.whitelist(methods=["POST"])
def give_kyc_consent() -> dict:
	from lending.loan_integrations.sample_verification import give_consent

	kyc = assert_sample_kyc(borrower())
	try:
		give_consent(kyc.kyc_request_id)
	except Exception as e:
		return {"ok": False, "message": str(e)}

	return {"ok": True, "redirect": "/secured-loan?step=kyc"}


def assert_sample_kyc(customer: str):
	from lending.loan_integrations.sample_verification import SampleKycAdapter

	if verification.adapter_key(verification.KYC) != SampleKycAdapter.key:
		raise frappe.PermissionError(_("Not permitted"))

	kyc = kyc_record(customer)
	if not kyc.kyc_request_id:
		frappe.throw(_("Please start your KYC from the portal."), frappe.ValidationError)

	return kyc


# Step 5: Pledge funds


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def send_pledge_otp() -> dict:
	customer = borrower()
	application = own_application(customer)
	if not kyc_record(customer).kyc_status == "Verified":
		frappe.throw(_("Please complete your KYC first."), frappe.ValidationError)

	with as_administrator():
		assignment = pledge_request(application)
		try:
			registry.send_lien_otp(assignment, refuse=True)
		except Refused as e:
			return refused(e)

	return {
		"ok": True,
		"message": _("We sent an OTP to the mobile number ending {0} to approve the lien.").format(
			customer_mobile(customer)[-4:]
		),
	}


def pledge_request(application):
	if application.docstatus == 0:
		application.status = "Open"
		application.submit()

	name = assignment_for(application.name)
	if not name:
		name = create_loan_security_assignment(loan_application=application.name)
		# create_loan_security_assignment tells staff in a message the borrower should not see.
		frappe.clear_messages()

	return frappe.get_doc("Loan Security Assignment", name)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def confirm_pledge() -> dict:
	customer = borrower()
	application = own_application(customer)
	name = assignment_for(application.name)
	if not name:
		frappe.throw(_("Please ask for the pledge OTP first."), frappe.ValidationError)

	# Read before as_administrator, which swaps form_dict out.
	otp = clean(frappe.form_dict.get("otp"))
	with as_administrator():
		try:
			registry.apply_lien_otp(frappe.get_doc("Loan Security Assignment", name), otp, refuse=True)
		except Refused as e:
			return refused(e)

	return {"ok": True}


def pledge_payload(application: str | None) -> dict:
	name = assignment_for(application) if application else None
	if not name:
		return {"marked": False, "status": "", "lines": []}

	doc = frappe.get_doc("Loan Security Assignment", name)

	return {
		"marked": doc.lien_status == "Marked",
		"status": doc.lien_status or "",
		"lines": [
			{
				"key": row.name,
				"scheme": row.loan_security_name or row.loan_security,
				"folio": row.folio_number or "",
				"units": number(row.qty),
				"value": money(row.amount),
				"lien": row.lien_reference or "",
			}
			for row in doc.securities
		],
	}


# Step 6: Bank details


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def save_bank_account() -> dict:
	customer = borrower()
	application = own_application(customer)
	assert_not_signed(application)
	if not pledge_payload(application.name)["marked"]:
		frappe.throw(_("Please pledge your units first."), frappe.ValidationError)

	account_number = "".join(character for character in clean(frappe.form_dict.get("account_number")) if character.isdigit())
	ifsc = clean(frappe.form_dict.get("ifsc")).upper()
	name = frappe.db.get_value("Customer", customer, "customer_name")

	try:
		output = verification.call(
			verification.BANK,
			"verify",
			{"account_number": account_number, "ifsc": ifsc, "name": name},
			application,
		)
	except Refused as e:
		return refused(e)

	if not output.get("verified"):
		return {"ok": False, "message": _("We could not verify this account.")}

	with as_administrator():
		account = bank_account(customer, name, account_number, ifsc, output.get("bank_name"))
	# A letter already sent names the old account, so it must be sent again.
	application.db_set({"bank_account": account, "sanction_letter": None})
	frappe.cache.delete_value(f"{ESIGN_PREFIX}:{application.name}")

	return {"ok": True}


def assert_not_signed(application):
	if application.signed_on:
		frappe.throw(
			_("You have signed your sanction letter, so its terms cannot change."), frappe.ValidationError
		)


def bank_account(customer: str, holder: str, account_number: str, ifsc: str, bank_name: str) -> str:
	existing = frappe.db.get_value(
		"Bank Account",
		{"party_type": "Customer", "party": customer, "bank_account_no": account_number},
		"name",
	)
	if existing:
		return existing

	bank_name = bank_name or _("Bank")
	if not frappe.db.exists("Bank", bank_name):
		frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert()

	account = frappe.get_doc(
		{
			"doctype": "Bank Account",
			"account_name": f"{holder} {account_number[-4:]}",
			"bank": bank_name,
			"party_type": "Customer",
			"party": customer,
			"bank_account_no": account_number,
			"branch_code": ifsc,
			"is_default": 1,
		}
	).insert()

	return account.name


def bank_payload(application: str | None) -> dict:
	account = frappe.db.get_value("Loan Application", application, "bank_account") if application else None
	if not account:
		return {}

	record = frappe.db.get_value("Bank Account", account, ["bank", "bank_account_no", "branch_code"], as_dict=True)

	return {
		"account": f"{'•' * 6}{(record.bank_account_no or '')[-4:]}",
		"bank": record.bank,
		"ifsc": record.branch_code or "",
	}


# Step 7: E-sign


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def send_esign_otp() -> dict:
	customer = borrower()
	application = own_application(customer)
	assert_not_signed(application)
	if not application.bank_account:
		frappe.throw(_("Please add your bank account first."), frappe.ValidationError)

	letter = sanction_letter(application)
	context = {
		"file_url": letter,
		"signer": {"name": application.applicant_name, "mobile": customer_mobile(customer)},
	}

	try:
		output = verification.call(verification.ESIGN, "send_otp", context, application)
	except Refused as e:
		return refused(e)

	frappe.cache.set_value(f"{ESIGN_PREFIX}:{application.name}", output.get("request_id"), expires_in_sec=ESIGN_TTL)

	return {
		"ok": True,
		"message": _("We sent an OTP to your Aadhaar-linked mobile number to sign the letter."),
	}


def sanction_letter(application) -> str:
	html = render(SANCTION_FORMAT, sanction_context(application))
	content = get_pdf(html)

	with as_administrator():
		saved = save_file(
			f"sanction-letter-{application.name}.pdf",
			content,
			"Loan Application",
			application.name,
			is_private=1,
		)
	application.db_set("sanction_letter", saved.file_url)

	return saved.file_url


def sanction_context(application) -> dict:
	brand = brand_payload()
	assignment = pledge_payload(application.name)
	ltv = frappe.db.get_value(
		"Loan Security Type",
		frappe.db.get_value("Loan Security", application.proposed_pledges[0].loan_security, "loan_security_type"),
		"loan_to_value_ratio",
	)
	product = frappe.db.get_value("Loan Product", application.loan_product, "product_name")
	terms = [
		{"label": _("Loan product"), "value": product or application.loan_product},
		{"label": _("Loan amount"), "value": money(application.loan_amount)},
		{"label": _("Rate of interest"), "value": _("{0}% a year").format(flt(application.rate_of_interest))},
	]
	if application.repayment_periods:
		terms.append({"label": _("Tenure"), "value": _("{0} months").format(application.repayment_periods)})
	if application.repayment_amount:
		terms.append({"label": _("Monthly instalment"), "value": money(application.repayment_amount)})

	return {
		"title": _("Sanction letter"),
		"subtitle": _("Application {0}").format(application.name),
		"brand_name": brand.get("brand_name", ""),
		"brand_logo": brand.get("brand_logo", ""),
		"support_email": brand.get("support_email", ""),
		"holder_name": application.applicant_name,
		"period_label": _("Date"),
		"period": long_date(application.posting_date),
		"accounts": [],
		"terms": terms,
		"pledges": [
			{key: line[key] for key in ("scheme", "folio", "units", "value", "lien")}
			for line in assignment["lines"]
		],
		"ltv": f"{number(ltv)}%" if ltv else _("the agreed share"),
		"bank_account": bank_payload(application.name).get("account", ""),
		"generated_on": long_date(nowdate()),
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def confirm_esign() -> dict:
	customer = borrower()
	application = own_application(customer)
	request_id = frappe.cache.get_value(f"{ESIGN_PREFIX}:{application.name}")
	if not request_id:
		return {"ok": False, "message": _("The OTP has expired. Please ask for a new one.")}

	try:
		output = verification.call(
			verification.ESIGN,
			"sign",
			{"request_id": request_id, "otp": clean(frappe.form_dict.get("otp"))},
			application,
		)
	except Refused as e:
		return refused(e)

	application.db_set({"esign_reference": output.get("reference"), "signed_on": now_datetime()})
	frappe.cache.delete_value(f"{ESIGN_PREFIX}:{application.name}")

	if (frappe.db.get_single_value("Lending Settings", "portal_loan_approval") or AUTOMATIC) == AUTOMATIC:
		return {"ok": True, "opened": open_loan(application.name)}

	return {"ok": True, "opened": False}


def open_loan(application: str) -> bool:
	save_point = f"portal_loan_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(save_point)

	try:
		with as_administrator():
			frappe.db.set_value("Loan Application", application, "status", "Approved")
			loan = create_loan(application)
			loan.posting_date = nowdate()
			loan.submit()
	except Exception as e:
		frappe.db.rollback(save_point=save_point)
		frappe.clear_last_message()
		if not isinstance(e, frappe.ValidationError):
			frappe.log_error(f"Portal loan for {application} did not open")
		frappe.get_doc("Loan Application", application).add_comment(
			"Comment", _("The portal could not open the loan, so it waits for staff: {0}").format(e)
		)
		return False

	frappe.db.release_savepoint(save_point)
	return True


def esign_payload(application: str | None) -> dict:
	if not application:
		return {}

	doc = frappe.db.get_value("Loan Application", application, ["sanction_letter", "signed_on"], as_dict=True)

	return {
		# Not the file's own URL: the borrower cannot read the Loan Application it is attached to.
		"letter": LETTER_URL if doc.sanction_letter else "",
		"signed_on": long_date(doc.signed_on),
	}


@frappe.whitelist()
def download_sanction_letter():
	application = journey_application(borrower())
	file_url = frappe.db.get_value("Loan Application", application, "sanction_letter") if application else None
	if not file_url:
		frappe.throw(_("Your sanction letter is not ready yet."), frappe.ValidationError)

	file = frappe.get_last_doc(
		"File",
		filters={
			"file_url": file_url,
			"attached_to_doctype": "Loan Application",
			"attached_to_name": application,
		},
	)
	frappe.local.response.filename = f"sanction-letter-{application}.pdf"
	frappe.local.response.filecontent = file.get_content()
	frappe.local.response.type = "pdf"


# Step 8: Your loan


def loan_payload(application: str | None) -> dict:
	name = loan_for(application) if application else None
	if not name:
		return {}

	loan = frappe.db.get_value(
		"Loan",
		name,
		["name", "loan_amount", "disbursed_amount", "status", "rate_of_interest", "loan_product"],
		as_dict=True,
	)
	available = drawable_amount(loan.name) if loan.status in DRAWABLE_STATUSES else 0
	pending = pending_disbursement(loan.name)

	return {
		"name": loan.name,
		"url": loan_url(loan.name),
		"amount": money(loan.loan_amount),
		"status": _(STATUS_LABELS.get(loan.status, loan.status)),
		"rate": _("{0}% a year").format(flt(loan.rate_of_interest)),
		"product": frappe.db.get_value("Loan Product", loan.loan_product, "product_name") or loan.loan_product,
		"disbursed": money(loan.disbursed_amount),
		"has_disbursed": flt(loan.disbursed_amount) > 0,
		"available": 0 if pending else flt(available, 2),
		"available_label": money(available),
		"pending_note": _("Your request for {0} is with our team. We will pay it out after review.").format(
			money(pending)
		)
		if pending
		else "",
	}


# After the loan step: the money


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def withdraw() -> dict:
	customer = borrower()
	application = journey_application(customer)
	loan = loan_for(application) if application else None
	if not loan:
		frappe.throw(_("Your loan is not open yet."), frappe.ValidationError)

	amount = flt(frappe.form_dict.get("amount"))
	automatic = (frappe.db.get_single_value("Lending Settings", "portal_loan_approval") or AUTOMATIC) == AUTOMATIC
	bank_account = frappe.db.get_value("Loan Application", application, "bank_account")

	with as_administrator():
		entry = disbursement(loan, amount, bank_account)
		if automatic:
			entry.submit()

	if automatic:
		return {
			"ok": True,
			"message": _("{0} is on its way to your {1} account.").format(
				money(amount), bank_payload(application).get("bank") or _("bank")
			),
		}

	return {"ok": True, "message": _("We have your request for {0}. We will pay it out after review.").format(money(amount))}


def disbursement(loan: str, amount: float, bank_account: str):
	check_drawdown(loan, amount)

	entry = new_loan_disbursement(
		loan, amount, repayment_start_date=first_due_date(loan), bank_account=bank_account
	)
	entry.insert(ignore_permissions=True)
	entry.add_comment("Comment", _("Requested by {0} from the borrower portal.").format(frappe.session.user))

	return entry


def first_due_date(loan: str):
	# A new loan has no schedule yet; a later withdrawal joins the running one.
	return next_due_date(loan) or frappe.db.get_value("Loan", loan, "repayment_start_date") or add_months(
		nowdate(), 1
	)


# Sign-up, for a visitor who has no login yet; it comes before the journey, not inside it


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=5, seconds=60 * 60, ip_based=True)
def register() -> dict:
	"""Open a borrower login from a verified mobile number, without a lead or its rule checks."""
	assert_public_apply_enabled()

	token = clean(frappe.form_dict.get("token"))
	mobile = verified_mobile(token)
	full_name = clean(frappe.form_dict.get("full_name"))
	email = login.login_email(frappe.form_dict.get("email"))

	if not full_name:
		frappe.throw(_("Please give your full name."), frappe.ValidationError)
	if frappe.db.exists("User", {"email": email}):
		frappe.throw(_("You already have an account. Please log in instead."), frappe.ValidationError)

	with as_administrator():
		user = frappe.new_doc("User")
		user.update(
			{
				"email": email,
				"first_name": full_name,
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		)
		user.insert(ignore_permissions=True)
		user.add_roles("Customer")

		# Always a new Customer: the email is not verified, so it cannot claim an existing one
		# and its loans. Staff link a borrower who already has one.
		customer = create_customer(full_name, "Individual", email, mobile)
		frappe.db.set_value("Customer", customer, "mobile_no", mobile)
		link_portal_user(customer, user.name)
		spend_token(token)

	if getattr(frappe.local, "login_manager", None):
		frappe.local.login_manager.login_as(user.name)

	return {"ok": True, "redirect": "/secured-loan"}

