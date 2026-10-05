# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow, get_workflow_name
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, getdate, strip_html, today

from lending.portal import login, preview
from lending.portal.accounts import CUSTOMER_TYPES, customer_for_applicant, link_portal_user
from lending.portal.core import (
	as_administrator,
	assert_portal_enabled,
	assert_public_apply_enabled,
	brand_payload,
	clean,
	get_loans,
	get_portal_customers,
	long_date,
	money,
	shell_payload,
	tracker_stage,
)

LEAD_SOURCE = "Portal"

LEAD_FIELDS = ("applicant_name", "email", "loan_product", "loan_amount")
OPTIONAL_LEAD_FIELDS = (
	"income",
	"proposed_tenure",
	"employment_type",
	"applicant_country",
	"pan",
	"date_of_birth",
)

EMPLOYMENT_TYPES = ("Salaried", "Self-employed")

# Loan Lead.mobile_number is a Phone field and frappe rejects it without a country code.
DEFAULT_COUNTRY_CODE = "+91"
NATIONAL_NUMBER_LENGTH = 10

APPLICANT_TYPES = ("Individual", "Business")
DEFAULT_APPLICANT_TYPE = "Individual"

BUSINESS_ONLY_FIELDS = ("company_name",)
PERSON_ONLY_FIELDS = ("date_of_birth", "employment_type")


# Scopes the OTP so a portal code cannot be spent against a desk-raised lead.
VERIFY_PURPOSE = "Portal Apply"
VERIFY_CHANNEL = "SMS"

VERIFICATION_TTL = 30 * 60
VERIFICATION_PREFIX = "portal-apply-verified"

ACCOUNT_TTL = 30 * 60
ACCOUNT_PREFIX = "portal-apply-account"
ACCOUNT_PURPOSE = "Portal Sign Up"

MINIMUM_AGE = 18
PAN_LENGTH = 10

# Free checks only: Pre-Qualification pulls a paid bureau report, so staff take a lead on from Desk.
AUTOMATIC_ACTIONS = ("Run Basic Rules",)


def offered_to(product_applicant_type: str | None, applicant_type: str) -> bool:
	# A blank portal_applicant_type offers the product to both.
	return not product_applicant_type or product_applicant_type == applicant_type


def product_card(row) -> dict:
	rate = _("{0}%").format(flt(row.rate_of_interest, 2))
	kind = _("Term loan") if row.is_term_loan else _("Credit line")

	return {
		"label": row.name,
		"value": row.name,
		"rate": rate,
		"rate_note": _("per year"),
		"summary": _("{0} per year · {1}").format(rate, kind),
		"ceiling": (
			_("Up to {0}").format(money(row.maximum_loan_amount)) if row.maximum_loan_amount else _("No limit")
		),
		"kind": kind,
	}


def portal_products() -> dict:
	products = frappe.get_all(
		"Loan Product",
		filters={"disabled": 0, "show_on_portal": 1},
		fields=["name", "rate_of_interest", "maximum_loan_amount", "is_term_loan", "portal_applicant_type"],
		order_by="rate_of_interest asc, name asc",
	)

	return {
		applicant_type: [
			product_card(row) for row in products if offered_to(row.portal_applicant_type, applicant_type)
		]
		for applicant_type in APPLICANT_TYPES
	}


@frappe.whitelist(allow_guest=True)  # nosemgrep
def get_apply_page() -> dict:
	assert_public_apply_enabled()

	return {
		**brand_payload(),
		"tagline": _("Simple · Secure · Transparent"),
		"heading": _("A loan that fits,{0}without the paperwork").format("\n"),
		"intro": _("Tell us what you need and see an indicative offer in about two minutes. Nothing is committed until you accept it."),
		"trust_points": [
			{"icon": "chart-no-axes", "title": _("No effect"), "note": _("on your credit score")},
			{"icon": "shield", "title": _("No obligation"), "note": _("to go ahead")},
			{"icon": "receipt-text", "title": _("No fee"), "note": _("to ask")},
		],
		"products": portal_products(),
		"start_title": _("Let's get started"),
		"start_note": _("A few questions, one at a time. Most people are through in two minutes."),
		"how_title": _("How it works"),
		"how_note": _("Get from application to an offer in a few simple steps."),
		"benefits": [
			{
				"icon": "file-text",
				"title": _("Answer a few questions"),
				"note": _("Six short steps. You can go back to any of them before you send it."),
			},
			{
				"icon": "search",
				"title": _("We review your application"),
				"note": _("Our team checks the details and runs the necessary checks."),
			},
			{
				"icon": "percent",
				"title": _("See your indicative offer"),
				"note": _("View a personalized offer before you decide anything."),
			},
		],
		"type_note": _("Whoever the money is for is who we run the numbers on."),
		"product_note": _("These are the products open to you. Pick the one that fits."),
		"verify_title": _("Your mobile number"),
		"verify_note": _("We send an OTP to check the number is yours. It is the only thing we need to start."),
		"code_note": _("Enter the OTP we sent you."),
		"details_title": _("About you"),
		"details_note": _("The more you tell us, the closer the indicative offer is to the real one. Only the starred fields are required."),
		"offer_title": _("Your indicative offer"),
		"account_title": _("Create your account"),
		"account_note": _("Verify your email to finish. You log in with a code we send to it, so there is no password to remember."),
	}


@frappe.whitelist(allow_guest=True)  # nosemgrep
def get_track_page() -> dict:
	assert_portal_enabled()

	return {
		**brand_payload(),
		"eyebrow": _("Track application"),
		"heading": _("Where has my application got to?"),
		"intro": "\n".join(
			(
				_("Enter the reference number we gave you and the mobile number you applied with."),
				_("We show both together so nobody else can look up your application."),
			)
		),
		"track_title": _("Find your application"),
	}


def with_country_code(number: str) -> str:
	digits = "".join(character for character in number if character.isdigit() or character == "+")

	if digits.startswith("+"):
		return digits

	bare = digits.lstrip("0")
	if len(bare) != NATIONAL_NUMBER_LENGTH:
		frappe.throw(_("Please give a valid mobile number."), frappe.ValidationError)

	return f"{DEFAULT_COUNTRY_CODE}{bare}"


def mask(number: str) -> str:
	return f"{'•' * max(len(number) - 2, 0)}{number[-2:]}" if len(number) > 2 else number


def telephony_otp():
	if "telephony" not in frappe.get_installed_apps():
		frappe.throw(_("Mobile verification is not switched on. Please try again later."))

	from telephony import otp

	return otp


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=5, seconds=60 * 60, ip_based=True)
def send_mobile_code() -> dict:
	preview.refuse_writes()
	assert_public_apply_enabled()

	mobile = with_country_code(clean(frappe.form_dict.get("mobile_number")))

	telephony_otp().send_otp(mobile, VERIFY_CHANNEL, purpose=VERIFY_PURPOSE)

	return {
		"sent": True,
		"mobile": mask(mobile),
		"headline": _("OTP sent"),
		"message": _("We sent an OTP to the number ending {0}.").format(mask(mobile)),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=10, seconds=60 * 60, ip_based=True)
def confirm_mobile_code() -> dict:
	"""Check the OTP and return the token submit_lead requires."""
	preview.refuse_writes()
	assert_public_apply_enabled()

	mobile = with_country_code(clean(frappe.form_dict.get("mobile_number")))
	code = clean(frappe.form_dict.get("otp"))

	if not code:
		frappe.throw(_("Please enter the OTP we sent you."), frappe.ValidationError)

	# Don't raise on failure: it would roll back the attempt telephony just recorded.
	result = telephony_otp().verify_otp(mobile, VERIFY_CHANNEL, code, purpose=VERIFY_PURPOSE)

	if not result.get("verified"):
		return {"verified": False, "message": _("That OTP is wrong or has expired.")}

	token = frappe.generate_hash(length=32)
	frappe.cache.set_value(
		f"{VERIFICATION_PREFIX}:{token}", mobile, expires_in_sec=VERIFICATION_TTL
	)

	return {
		"verified": True,
		"token": token,
		"mobile": mask(mobile),
		"message": _("Number verified. Now tell us what you need."),
	}


class VerificationExpiredError(frappe.ValidationError):
	pass


def verified_mobile(token: str) -> str:
	# Read only; spend_token consumes it after the lead saves.
	mobile = frappe.cache.get_value(f"{VERIFICATION_PREFIX}:{token}") if token else None

	if not mobile:
		frappe.throw(
			_("Your confirmation has expired. Please verify your mobile number again."),
			VerificationExpiredError,
		)

	return mobile


def claim(key: str) -> bool:
	# Redis DEL reports what it removed, so only one of two racing requests gets True.
	return bool(frappe.cache.delete(frappe.cache.make_key(key)))


def spend_token(token: str):
	if not claim(f"{VERIFICATION_PREFIX}:{token}"):
		frappe.throw(
			_("Your confirmation has expired. Please verify your mobile number again."),
			VerificationExpiredError,
		)


def read_product(name: str, amount: float, applicant_type: str = DEFAULT_APPLICANT_TYPE) -> dict:
	# Same filter as portal_products, so a hidden product can't be applied for by name.
	product = frappe.db.get_value(
		"Loan Product",
		{"name": name, "disabled": 0, "show_on_portal": 1},
		["name", "maximum_loan_amount", "portal_applicant_type"],
		as_dict=True,
	)
	if not product or not offered_to(product.portal_applicant_type, applicant_type):
		frappe.throw(_("Please choose a product from the list."), frappe.ValidationError)

	if product.maximum_loan_amount and amount > flt(product.maximum_loan_amount):
		frappe.throw(
			_("The most you can apply for on this product is {0}.").format(
				money(product.maximum_loan_amount)
			),
			frappe.ValidationError,
		)

	return product


def read_date_of_birth(value: str):
	if not value:
		return None

	try:
		date_of_birth = getdate(value)
	except Exception:
		frappe.throw(_("Please give your date of birth as a date."), frappe.ValidationError)

	if date_of_birth >= getdate(today()):
		frappe.throw(_("Please check your date of birth."), frappe.ValidationError)

	if (getdate(today()).year - date_of_birth.year) < MINIMUM_AGE:
		frappe.throw(
			_("You have to be at least {0} to apply.").format(MINIMUM_AGE), frappe.ValidationError
		)

	return date_of_birth


def read_applicant_type() -> str:
	asked = clean(frappe.form_dict.get("applicant_type"))

	return asked if asked in APPLICANT_TYPES else DEFAULT_APPLICANT_TYPE


def read_optional(applicant_type: str, company_name: str) -> dict:
	person = applicant_type == "Individual"
	employment = clean(frappe.form_dict.get("employment_type"))
	country = clean(frappe.form_dict.get("applicant_country"))
	pan = clean(frappe.form_dict.get("pan")).upper()

	if pan and len(pan) != PAN_LENGTH:
		frappe.throw(_("A PAN is {0} characters.").format(PAN_LENGTH), frappe.ValidationError)

	if not person and not company_name:
		frappe.throw(_("Please give the company's name."), frappe.ValidationError)

	return {
		"applicant_type": applicant_type,
		"company_name": None if person else company_name,
		"income": flt(frappe.form_dict.get("income")) or None,
		"proposed_tenure": cint(frappe.form_dict.get("proposed_tenure")) or None,
		# "" not None: frappe fills a None Select with its first option (Salaried) on insert.
		"employment_type": employment if (person and employment in EMPLOYMENT_TYPES) else "",
		"applicant_country": country if country and frappe.db.exists("Country", country) else None,
		"pan": pan or None,
		"date_of_birth": read_date_of_birth(clean(frappe.form_dict.get("date_of_birth"))) if person else None,
	}


def read_submission() -> dict:
	data = {field: clean(frappe.form_dict.get(field)) for field in LEAD_FIELDS}

	missing = [field for field, value in data.items() if not value]
	if missing:
		frappe.throw(_("Please fill in every required field."), frappe.ValidationError)

	if not frappe.utils.validate_email_address(data["email"]):
		frappe.throw(_("Please give a valid email address."), frappe.ValidationError)

	applicant_type = read_applicant_type()
	data.update(read_loan_request(applicant_type, clean(frappe.form_dict.get("company_name"))))

	return data


def read_loan_request(applicant_type: str, company_name: str) -> dict:
	product = clean(frappe.form_dict.get("loan_product"))
	amount = flt(frappe.form_dict.get("loan_amount"))

	if not product:
		frappe.throw(_("Please fill in every required field."), frappe.ValidationError)

	if amount <= 0:
		frappe.throw(_("Please give the amount you need."), frappe.ValidationError)

	read_product(product, amount, applicant_type)

	return {
		"loan_product": product,
		"loan_amount": amount,
		**read_optional(applicant_type, company_name),
	}


def settle_lead(lead: str, mobile: str):
	run_automatic_rules(lead)
	mark_mobile_verified(lead, mobile)


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=5, seconds=60 * 60, ip_based=True)
def submit_lead() -> dict:
	"""Create a draft Loan Lead (a submitted one skips the rule steps) and return its offer."""
	preview.refuse_writes()
	assert_public_apply_enabled()

	token = clean(frappe.form_dict.get("token"))
	data = read_submission()
	mobile = verified_mobile(token)

	lead = frappe.new_doc("Loan Lead")
	lead.update({**data, "mobile_number": mobile, "lead_source": LEAD_SOURCE})
	lead.insert(ignore_permissions=True)
	spend_token(token)

	settle_lead(lead.name, mobile)
	lead.reload()

	offer = present_offer(lead)
	offer["account_token"] = issue_account_token(lead.name)

	return offer


def run_automatic_rules(lead: str):
	if not get_workflow_name("Loan Lead"):
		return

	# Each step is a Loan Officer action; the lead and actions are fixed, not from the request.
	with as_administrator():
		apply_actions(lead)


def apply_actions(lead: str):
	# One savepoint for all steps, so a knocked-out lead keeps no pre-qualification offer.
	save_point = f"portal_lead_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(save_point)

	for action in AUTOMATIC_ACTIONS:
		try:
			apply_workflow(frappe.get_doc("Loan Lead", lead), action)
		except Exception as e:
			frappe.db.rollback(save_point=save_point)
			frappe.clear_last_message()
			note_stopped_rules(lead, action, e)
			return

	frappe.db.release_savepoint(save_point)


def note_stopped_rules(lead: str, action: str, error: Exception):
	# A ValidationError is a rule's decision; anything else is a fault.
	if not isinstance(error, frappe.ValidationError):
		frappe.log_error(f"Portal lead {lead} failed at {action}")

	frappe.get_doc("Loan Lead", lead).add_comment(
		"Comment",
		_("The portal's automatic checks stopped at {0}: {1}").format(
			action, strip_html(str(error)) or _("no reason was given.")
		),
	)


def mark_mobile_verified(lead: str, mobile: str):
	# Written after the rules: set_verification_statuses resets it to Pending on every validate of a new lead.
	frappe.db.set_value(
		"Loan Lead",
		{"name": lead, "mobile_number": mobile},
		"mobile_verification_status",
		"Verified",
	)


def present_offer(lead) -> dict:
	status = lead.prequalification_status or ""
	offer = []

	if lead.indicative_amount:
		offer.append({"label": _("Indicative amount"), "value": money(lead.indicative_amount)})
	if lead.indicative_roi:
		offer.append(
			{"label": _("Indicative rate"), "value": _("{0}% p.a.").format(flt(lead.indicative_roi, 2))}
		)
	if lead.indicative_tenure:
		offer.append(
			{"label": _("Indicative tenure"), "value": _("{0} months").format(cint(lead.indicative_tenure))}
		)

	if status == "Pre-Qualified" and offer:
		headline = _("Good news, you are pre-qualified")
		message = _(
			"This is indicative. The final terms come with your loan agreement, "
			"after we have checked your documents."
		)
	elif status == "Not Pre-Qualified":
		headline = _("We cannot offer you a loan just now")
		message = _(
			"Thank you for asking. You are welcome to apply again later, and your "
			"account will keep this enquiry in the meantime."
		)
	else:
		headline = _("Thank you, we have your enquiry")
		message = _("Our team will come back to you shortly.")

	action = ""

	return {
		"reference": lead.name,
		"tone": "danger" if status == "Not Pre-Qualified" else "ok",
		"headline": headline,
		"message": message,
		"offer": offer,
		"action": action,
		"reference_note": _("Keep reference {0} to track your application.").format(lead.name),
	}


def issue_account_token(lead: str) -> str:
	# Without it, anyone who guessed a reference could open an account against it.
	token = frappe.generate_hash(length=32)
	frappe.cache.set_value(f"{ACCOUNT_PREFIX}:{token}", lead, expires_in_sec=ACCOUNT_TTL)

	return token


def lead_for_account(token: str) -> str:
	# Read only, so a wrong code can be retried.
	if not token:
		frappe.throw(_("Please finish your application first."), frappe.ValidationError)

	lead = frappe.cache.get_value(f"{ACCOUNT_PREFIX}:{token}")

	if not lead:
		frappe.throw(
			_("This has taken too long. Please apply again to open an account."),
			frappe.ValidationError,
		)

	return lead


def spend_account_token(token: str):
	if not claim(f"{ACCOUNT_PREFIX}:{token}"):
		frappe.throw(
			_("This has taken too long. Please apply again to open an account."),
			frappe.ValidationError,
		)


def account_email() -> str:
	return login.login_email(frappe.form_dict.get("email"))


def refuse_existing_account():
	frappe.throw(_("You already have an account. Please log in instead."), frappe.ValidationError)


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=5, seconds=60 * 60, ip_based=True)
def send_account_code() -> dict:
	"""Email a code that proves the borrower owns the address their account will log in with."""
	preview.refuse_writes()
	assert_public_apply_enabled()

	lead_for_account(clean(frappe.form_dict.get("token")))
	email = account_email()

	# The login form already says whether a borrower exists; a desk user must look like a new address.
	if login.portal_user(email):
		refuse_existing_account()
	if not frappe.db.exists("User", {"email": email}):
		login.telephony_otp().send_otp(email, login.LOGIN_CHANNEL, purpose=ACCOUNT_PURPOSE)

	return {
		"sent": True,
		"message": _("We sent a code to {0}. It expires in {1} minutes.").format(
			email, login.code_expiry_minutes()
		),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=10, seconds=60 * 60, ip_based=True)
def create_account() -> dict:
	"""Create the login for the lead the account token names, and sign the borrower in."""
	preview.refuse_writes()
	assert_public_apply_enabled()

	# Read once: the writes below leave form_dict without it by the time it is spent.
	token = clean(frappe.form_dict.get("token"))
	lead_name = lead_for_account(token)
	email = account_email()
	code = clean(frappe.form_dict.get("otp"))

	if not code:
		frappe.throw(_("Please enter the code we sent you."), frappe.ValidationError)

	# Don't raise on failure: it would roll back the attempt telephony just recorded.
	result = login.telephony_otp().verify_otp(
		email, login.LOGIN_CHANNEL, code, purpose=ACCOUNT_PURPOSE
	)
	if not result.get("verified"):
		return {"verified": False, "message": _("That code is wrong or has expired.")}

	# Only after the code: checked earlier, a wrong code would reveal which addresses have a User.
	if frappe.db.exists("User", {"email": email}):
		refuse_existing_account()

	lead = frappe.db.get_value(
		"Loan Lead",
		lead_name,
		["applicant_name", "company_name", "applicant_type", "mobile_number"],
		as_dict=True,
	)

	# ignore_permissions is not enough: Customer.on_update calls an API that re-checks permissions.
	caller = frappe.session.user
	frappe.set_user("Administrator")  # nosemgrep
	try:
		# The confirmed address wins, so leads_for_login finds this lead from the new login.
		frappe.db.set_value("Loan Lead", lead_name, "email", email)

		user = frappe.new_doc("User")
		user.update(
			{
				"email": email,
				"first_name": lead.company_name or lead.applicant_name,
				# Not mobile_no: it is unique on User, and family members share a number.
				# The Customer's Contact keeps it instead.
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		)
		user.insert(ignore_permissions=True)
		user.add_roles("Customer")

		customer = customer_for_applicant(
			lead.company_name or lead.applicant_name,
			lead.applicant_type,
			email,
			lead.mobile_number,
		)
		link_portal_user(customer, user.name)
		spend_account_token(token)
	finally:
		frappe.set_user(caller)  # nosemgrep

	# login_manager exists only inside a web request, not in tests or the console.
	if getattr(frappe.local, "login_manager", None):
		frappe.local.login_manager.login_as(user.name)

	return {
		"verified": True,
		"headline": _("Your account is ready"),
		"message": _("You are signed in as {0}.").format(user.name),
		"offer": [],
		"reference_note": "",
		"redirect": "/borrower-portal/overview",
	}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60)
def create_customer_lead() -> dict:
	"""Like submit_lead for a logged-in borrower; identity comes from their Customer, not the request."""
	preview.refuse_writes()
	customer = read_own_customer()
	applicant = applicant_for(customer)
	data = read_loan_request(applicant["applicant_type"], applicant["company_name"])

	# Loan Lead grants create to System Manager only.
	lead = frappe.new_doc("Loan Lead")
	lead.update({**data, **applicant, "customer": customer, "lead_source": LEAD_SOURCE})
	lead.insert(ignore_permissions=True)

	settle_lead(lead.name, applicant["mobile_number"])
	lead.reload()

	return present_offer(lead)


def read_own_customer() -> str:
	customers = get_portal_customers()
	asked = clean(frappe.form_dict.get("customer"))

	if not asked and len(customers) == 1:
		return customers[0]

	if asked not in customers:
		frappe.throw(_("Please choose who the loan is for."), frappe.ValidationError)

	return asked


def applicant_for(customer: str) -> dict:
	applicant = on_file(customer)

	if not applicant["mobile_number"]:
		frappe.throw(
			_("We have no mobile number for you. Please add one to your profile first."),
			frappe.ValidationError,
		)

	applicant["mobile_number"] = with_country_code(applicant["mobile_number"])

	return applicant


def on_file(customer: str) -> dict:
	record = frappe.db.get_value(
		"Customer", customer, ["customer_name", "customer_type", "mobile_no"], as_dict=True
	)
	user = frappe.db.get_value(
		"User", frappe.session.user, ["email", "full_name", "mobile_no"], as_dict=True
	)
	business = record.customer_type == CUSTOMER_TYPES["Business"]

	return {
		"applicant_type": "Business" if business else "Individual",
		"applicant_name": user.full_name if business else record.customer_name,
		"company_name": record.customer_name if business else None,
		# The login's email, so leads_for_login finds this lead.
		"email": user.email,
		"mobile_number": record.mobile_no or user.mobile_no or "",
	}


@frappe.whitelist()
def get_new_application_page() -> dict:
	customers = get_portal_customers()

	payload = shell_payload(_("New application"), "", get_loans(customers) if customers else [])
	payload.update(
		{
			"breadcrumbs": [
				{"label": _("Application"), "route": "/borrower/applications"},
				{"label": _("New application"), "route": ""},
			],
			"applicants": [applicant_option(customer) for customer in customers],
			"products": portal_products(),
			"employment_types": [{"label": _(kind), "value": kind} for kind in EMPLOYMENT_TYPES],
			"no_mobile_note": _(
				"We have no mobile number for you. Add one in Personal details before you apply."
			),
		}
	)

	return payload


def applicant_option(customer: str) -> dict:
	applicant = on_file(customer)

	return {
		"value": customer,
		"label": applicant["company_name"] or applicant["applicant_name"],
		"applicant_type": applicant["applicant_type"],
		"has_mobile": bool(applicant["mobile_number"]),
		"identity": {
			"applicant_name": applicant["applicant_name"],
			"company_name": applicant["company_name"] or "",
			"email": applicant["email"],
			"mobile_number": applicant["mobile_number"],
		},
		"answers": last_answers(customer, applicant),
	}


def last_answers(customer: str, applicant: dict) -> dict:
	# Guest enquiries match on applicant type too, so a company never inherits the owner's DOB.
	fields = ["income", "employment_type", "date_of_birth", "pan", "proposed_tenure"]
	guest_enquiry = {
		"email": applicant["email"],
		"applicant_type": applicant["applicant_type"],
		"customer": ("is", "not set"),
	}
	lead = (
		frappe.db.get_value(
			"Loan Lead", {"customer": customer}, fields, order_by="creation desc", as_dict=True
		)
		or frappe.db.get_value("Loan Lead", guest_enquiry, fields, order_by="creation desc", as_dict=True)
		or frappe._dict()
	)

	# Only a PAN-length tax_id is a PAN; a GSTIN is longer.
	tax_id = frappe.db.get_value("Customer", customer, "tax_id") or ""

	return {
		"income": flt(lead.income) or "",
		"employment_type": lead.employment_type or "",
		"date_of_birth": str(lead.date_of_birth or ""),
		"pan": lead.pan or (tax_id if len(tax_id) == PAN_LENGTH else ""),
		"proposed_tenure": cint(lead.proposed_tenure) or "",
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=10, seconds=60 * 60, ip_based=True)
def track_application() -> dict:
	"""Status by reference number and mobile number, both of which must match."""
	assert_portal_enabled()

	reference = clean(frappe.form_dict.get("reference"))
	mobile = clean(frappe.form_dict.get("mobile_number"))

	if not reference or not mobile:
		frappe.throw(
			_("Please give both your reference number and your mobile number."),
			frappe.ValidationError,
		)

	mobile = with_country_code(mobile)

	lead = frappe.db.get_value(
		"Loan Lead",
		{"name": reference, "mobile_number": mobile},
		[
			"name",
			"applicant_name",
			"loan_product",
			"loan_amount",
			"status",
			"prequalification_status",
			"creation",
		],
		as_dict=True,
	)

	# One refusal for every miss, so this can't be used as a reference-number oracle.
	if not lead:
		frappe.throw(
			_("We could not find an application with those details."), frappe.ValidationError
		)

	return {
		"reference": lead.name,
		"headline": _("Application {0}").format(lead.name),
		"message": _("{0}, raised on {1}").format(lead.loan_product, long_date(lead.creation)),
		"offer": [
			{"label": _("Amount sought"), "value": money(lead.loan_amount)},
			{"label": _("Stage"), "value": tracker_stage(lead)},
		],
		"steps": tracker_steps(lead),
		"reference_note": _("Log in to see more once your account is open."),
	}


def tracker_steps(lead: dict) -> list[dict]:
	# state is one of "done", "now", "todo", "stopped".
	declined = lead.prequalification_status == "Not Pre-Qualified"
	qualified = lead.prequalification_status == "Pre-Qualified"

	def as_step(title: str, note: str, state: str) -> dict:
		return {"title": title, "note": note, "state": state}

	steps = [
		as_step(_("Enquiry sent"), _("We have your details and your number is verified."), "done")
	]

	if declined:
		steps.append(
			as_step(
				_("Not taken forward"),
				_("We cannot offer you a loan on these details. You may apply again later."),
				"stopped",
			)
		)
		return steps

	steps.append(
		as_step(
			_("Checked against our rules"),
			_("You are pre-qualified for an indicative offer.")
			if qualified
			else _("Our team is looking at your enquiry."),
			"done" if qualified else "now",
		)
	)
	steps.append(
		as_step(
			_("Your full application"),
			_("Create an account and finish the form to go ahead."),
			"now" if qualified else "todo",
		)
	)
	steps.append(as_step(_("Decision"), _("We tell you yes or no, with the terms."), "todo"))

	return steps
