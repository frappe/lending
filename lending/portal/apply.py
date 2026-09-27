# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The public front of the borrower portal: apply, and track what you applied for.

These are the only endpoints a stranger can reach, which PORTAL_PLAN.md section 8
caps deliberately. Every one is rate limited by IP. Neither page accepts a doctype or
a fieldname from the browser: every field is read by name from a fixed list, and Loan
Lead is inserted with ignore_permissions because the doctype grants create rights to
System Manager only.

Applying runs in three steps, which is the order every lender we compared uses:

1. The visitor gives a mobile number and we send a code to it.
2. The visitor types the code back.
3. The visitor fills in the rest, and only then does a Loan Lead exist.

Verifying before the lead is created is deliberate. Loan Lead makes name, email,
product and amount mandatory, so a lead cannot exist at step 1 without inventing
values for four fields the visitor has not given yet. Verification therefore runs
against the bare number through the telephony app, and the lead is stamped Verified
once it is created. The proof that step 2 happened is a random token held in the cache
for VERIFICATION_TTL, so step 3 cannot be called on its own.

A borrower who is already logged in skips the first two: create_customer_lead reads
who they are off their Customer and makes the same draft lead. It is the one endpoint here
a guest cannot call.

Tracking matches the reference number AND the mobile number before it answers, and
returns the same refusal whether the reference is wrong, the mobile is wrong, or the
application does not exist. A tracker that distinguishes those cases is a tool for
guessing other people's reference numbers.
"""

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow, get_workflow_name
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, getdate, strip_html, today

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

# The only fields a visitor may fill. Anything else on Loan Lead is ours to set.
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

# Loan Lead.mobile_number is a Phone field, which frappe rejects without a country
# code. A portal visitor should not have to know that, so a bare number gets the
# default prefix. PORTAL_PLAN.md section 9 puts portal settings on Lending Settings;
# this belongs there once those fields exist.
DEFAULT_COUNTRY_CODE = "+91"
NATIONAL_NUMBER_LENGTH = 10

# Loan Lead.applicant_type. A person borrows in their own name; a business borrows in
# the company's, and Loan Lead zeroes the age for one, so the two are not the same form.
APPLICANT_TYPES = ("Individual", "Business")
DEFAULT_APPLICANT_TYPE = "Individual"

# What a company is asked instead of a date of birth and a job.
BUSINESS_ONLY_FIELDS = ("company_name",)
PERSON_ONLY_FIELDS = ("date_of_birth", "employment_type")


# Scopes the OTP inside the telephony app, so a code minted here cannot be spent
# against a desk-raised lead, and vice versa.
VERIFY_PURPOSE = "Portal Apply"
VERIFY_CHANNEL = "SMS"

# Long enough to fill in a form after reading a text message, short enough that a
# leaked token is worth little.
VERIFICATION_TTL = 30 * 60
VERIFICATION_PREFIX = "portal-apply-verified"

# The second token: proof that this browser is the one that just created this lead,
# and therefore the one entitled to open an account against it. Short, because the
# account is made on the next click.
ACCOUNT_TTL = 30 * 60
ACCOUNT_PREFIX = "portal-apply-account"

MINIMUM_AGE = 18
PAN_LENGTH = 10

# The Loan Lead Workflow steps a portal lead takes by itself, in order. Converting it
# to an application stays with staff.
AUTOMATIC_ACTIONS = ("Run Basic Rules", "Run Pre-Qualification Rules", "Run Knockout Rules")

# A floor of our own. System Settings.minimum_password_score is set on this site and
# a single character still went through, so a public endpoint that creates logins
# cannot lean on it. Frappe's strength test still applies on top of this.
MINIMUM_PASSWORD_LENGTH = 8


def offered_to(product_applicant_type: str | None, applicant_type: str) -> bool:
	"""Loan Product.portal_applicant_type. Blank offers the product to both."""
	return not product_applicant_type or product_applicant_type == applicant_type


def product_card(row) -> dict:
	return {
		"label": row.name,
		"value": row.name,
		"rate": _("{0}%").format(flt(row.rate_of_interest, 2)),
		"rate_note": _("per year"),
		"ceiling": money(row.maximum_loan_amount) if row.maximum_loan_amount else _("No set limit"),
		"kind": _("Term loan") if row.is_term_loan else _("Credit line"),
	}


def portal_products() -> dict:
	"""Keyed by applicant type, so a page lists the products open to whoever is borrowing,
	and nothing else."""
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


@frappe.whitelist(allow_guest=True)
def get_apply_page() -> dict:
	assert_public_apply_enabled()

	return {
		**brand_payload(),
		"tagline": _("Simple · Secure · Transparent"),
		# The break is where the heading turns, so the page keeps it rather than letting
		# the column's width decide.
		"heading": _("A loan that fits,\nwithout the paperwork"),
		"intro": _(
			"Tell us what you need and see an indicative offer in about two minutes. "
			"Nothing is committed until you accept it."
		),
		"trust_points": [
			{"icon": "chart-no-axes", "title": _("No effect"), "note": _("on your credit score")},
			{"icon": "shield", "title": _("No obligation"), "note": _("to go ahead")},
			{"icon": "receipt-text", "title": _("No fee"), "note": _("to ask")},
		],
		"products": portal_products(),
		# The opening screen asks for nothing. It says what this is, how long it takes,
		# and offers one button, because a form is work and an invitation is not.
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
		"verify_note": _(
			"We send an OTP to check the number is yours. "
			"It is the only thing we need to start."
		),
		"code_note": _("Enter the OTP we sent you."),
		"details_title": _("About you"),
		"details_note": _(
			"The more you tell us, the closer the indicative offer is to the real one. "
			"Only the starred fields are required."
		),
		"offer_title": _("Your indicative offer"),
		"account_title": _("Keep track of this"),
		"account_note": _(
			"Your number is confirmed, so all that is left is a password. "
			"Your account shows this application and, once it is drawn, your loan."
		),
	}


@frappe.whitelist(allow_guest=True)
def get_track_page() -> dict:
	assert_portal_enabled()

	return {
		**brand_payload(),
		"eyebrow": _("Track application"),
		"heading": _("Where has my application got to?"),
		# One sentence to a line, as the page sets them.
		"intro": "\n".join(
			(
				_("Enter the reference number we gave you and the mobile number you applied with."),
				_("We show both together so nobody else can look up your application."),
			)
		),
		"track_title": _("Find your application"),
	}


def with_country_code(number: str) -> str:
	"""A Phone field needs a country code; a visitor types the number they know."""
	digits = "".join(character for character in number if character.isdigit() or character == "+")

	if digits.startswith("+"):
		return digits

	bare = digits.lstrip("0")
	if len(bare) != NATIONAL_NUMBER_LENGTH:
		frappe.throw(_("Please give a valid mobile number."), frappe.ValidationError)

	return f"{DEFAULT_COUNTRY_CODE}{bare}"


def mask(number: str) -> str:
	"""Show the last two digits only, so the page can confirm which number it used."""
	return f"{'•' * max(len(number) - 2, 0)}{number[-2:]}" if len(number) > 2 else number


# --- step 1 and 2: prove the number is yours ----------------------------------------


def telephony_otp():
	if "telephony" not in frappe.get_installed_apps():
		frappe.throw(_("Mobile verification is not switched on. Please try again later."))

	from telephony import otp

	return otp


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60, ip_based=True)
def send_mobile_code() -> dict:
	assert_public_apply_enabled()

	mobile = with_country_code(clean(frappe.form_dict.get("mobile_number")))

	telephony_otp().send_otp(mobile, VERIFY_CHANNEL, purpose=VERIFY_PURPOSE)

	return {
		"sent": True,
		"mobile": mask(mobile),
		"headline": _("OTP sent"),
		"message": _("We sent an OTP to the number ending {0}.").format(mask(mobile)),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60, ip_based=True)
def confirm_mobile_code() -> dict:
	"""Check the code and hand back the token step 3 requires."""
	assert_public_apply_enabled()

	mobile = with_country_code(clean(frappe.form_dict.get("mobile_number")))
	code = clean(frappe.form_dict.get("otp"))

	if not code:
		frappe.throw(_("Please enter the OTP we sent you."), frappe.ValidationError)

	# A failed verification comes back as a value, not an exception, and turning it
	# into a raise would roll back the attempt the telephony app just recorded.
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
		"message": _("Number confirmed. Now tell us what you need."),
	}


class VerificationExpiredError(frappe.ValidationError):
	"""The proof of the number is gone, so the page sends the visitor back to verify."""


def verified_mobile(token: str) -> str:
	"""The number step 2 proved, or a refusal. Read only: spend_token uses it up."""
	mobile = frappe.cache.get_value(f"{VERIFICATION_PREFIX}:{token}") if token else None

	if not mobile:
		frappe.throw(
			_("Your confirmation has expired. Please verify your mobile number again."),
			VerificationExpiredError,
		)

	return mobile


def claim(key: str) -> bool:
	"""Delete a token, and say whether this request was the one that deleted it.

	Redis DEL reports what it removed, so of two requests racing with one token only
	one gets True. The other throws, and whatever it wrote rolls back.
	"""
	return bool(frappe.cache.delete(frappe.cache.make_key(key)))


def spend_token(token: str):
	"""One token, one lead. Left alive it would be a reusable licence to insert rows.

	Spent after the lead is saved, so a lead that fails to save leaves the visitor
	verified.
	"""
	if not claim(f"{VERIFICATION_PREFIX}:{token}"):
		frappe.throw(
			_("Your confirmation has expired. Please verify your mobile number again."),
			VerificationExpiredError,
		)


# --- step 3: the lead ---------------------------------------------------------------


def read_product(name: str, amount: float, applicant_type: str = DEFAULT_APPLICANT_TYPE) -> dict:
	"""A Link field is a name, so it is checked against the table rather than trusted.

	The same filter as the list above, applicant type included. Filtering only the list
	would leave the hidden products one guessed name away from being applied for.
	"""
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
	"""Optional, but a date that makes the applicant a child is a typo worth catching."""
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
	"""The fields that sharpen the offer. A bad value here is dropped, never fatal --
	except where it is plainly a mistake, which the readers above throw on.

	Which fields apply depends on who is borrowing. A company has no date of birth and
	no employment, and Loan Lead.set_age zeroes the age for one anyway, so those are
	dropped rather than stored as noise against a business.
	"""
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
		# Empty string, not None. Frappe replaces a None Select with the field's first
		# option on insert, so a company would be recorded as Salaried and a person who
		# chose nothing would be recorded as one too. An empty string survives.
		"employment_type": employment if (person and employment in EMPLOYMENT_TYPES) else "",
		"applicant_country": country if country and frappe.db.exists("Country", country) else None,
		"pan": pan or None,
		"date_of_birth": read_date_of_birth(clean(frappe.form_dict.get("date_of_birth"))) if person else None,
	}


def read_submission() -> dict:
	"""Pull the known fields out of the request and refuse anything short of complete."""
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
	"""What is being asked for, as opposed to who is asking."""
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
	"""Run the workflow's rule steps on a fresh draft, then stamp the number verified."""
	run_automatic_rules(lead)
	mark_mobile_verified(lead, mobile)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60, ip_based=True)
def submit_lead() -> dict:
	"""Create a draft Loan Lead, run its workflow rules, and hand back what they decided.

	The lead stays a draft: the workflow's rule steps only apply to one, and a submitted
	lead jumps straight to Qualified with none of them run. The indicative offer is read
	back off the saved document rather than computed here. The portal owns no credit
	policy.
	"""
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
	"""Take the lead through AUTOMATIC_ACTIONS, or leave it at Incoming with a note.

	All three steps share one savepoint. A lead the knockout rules stop keeps no
	pre-qualification verdict, so the offer on this page and the tracker cannot show an
	offer the next rule took back. Staff read the note and re-run the steps from the desk.
	"""
	if not get_workflow_name("Loan Lead"):
		return

	# Elevated because every step is a Loan Officer action and the caller is a guest or a
	# borrower. The lead is the one this request just made, and the actions are fixed
	# above rather than read from the request.
	with as_administrator():
		apply_actions(lead)


def apply_actions(lead: str):
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
	# A rule saying no raises a ValidationError, which is a decision for staff to read.
	# Anything else is a fault and goes to the Error Log as well.
	if not isinstance(error, frappe.ValidationError):
		frappe.log_error(f"Portal lead {lead} failed at {action}")

	frappe.get_doc("Loan Lead", lead).add_comment(
		"Comment",
		_("The portal's automatic checks stopped at {0}: {1}").format(
			action, strip_html(str(error)) or _("no reason was given.")
		),
	)


def mark_mobile_verified(lead: str, mobile: str):
	"""Stamp the status after the document settles, never on the document itself.

	Loan Lead.set_verification_statuses resets both statuses to Pending inside validate
	whenever the recipient changed, which on a new document is always. Writing Verified
	before insert or before the rules run is therefore erased by the next validate. Writing it
	afterwards, filtered on the number it belongs to, is what survives -- the same shape
	Loan Lead.mark_otp_status uses.
	"""
	frappe.db.set_value(
		"Loan Lead",
		{"name": lead, "mobile_number": mobile},
		"mobile_verification_status",
		"Verified",
	)


def present_offer(lead) -> dict:
	"""The offer, the decline or the holding message -- whichever the rules produced."""
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
		# No reason codes: they are internal decision output, not a borrower message.
		message = _(
			"Thank you for asking. You are welcome to apply again later, and your "
			"account will keep this enquiry in the meantime."
		)
	else:
		headline = _("Thank you, we have your enquiry")
		message = _("Our team will come back to you shortly.")

	# Nothing to click through to: the next step is on this page. The offer card keeps
	# the key so its markup does not have to change.
	action = ""

	return {
		"reference": lead.name,
		"headline": headline,
		"message": message,
		"offer": offer,
		"action": action,
		"reference_note": _("Keep reference {0} to track your application.").format(lead.name),
	}


# --- step 4: the account ------------------------------------------------------------


def issue_account_token(lead: str) -> str:
	"""Proof that this browser is the one that just raised this lead.

	Without it, create_account would take any reference number, and anybody who
	guessed one could open an account against somebody else's application.
	"""
	token = frappe.generate_hash(length=32)
	frappe.cache.set_value(f"{ACCOUNT_PREFIX}:{token}", lead, expires_in_sec=ACCOUNT_TTL)

	return token


def lead_for_account(token: str) -> str:
	"""The lead the token was issued for. Read only: spend_account_token uses it up,
	once the account exists, so a refused password can be retried."""
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
	"""One token, one account."""
	if not claim(f"{ACCOUNT_PREFIX}:{token}"):
		frappe.throw(
			_("This has taken too long. Please apply again to open an account."),
			frappe.ValidationError,
		)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60, ip_based=True)
def create_account() -> dict:
	"""Open the borrower's account at the end of a successful application.

	Frappe's own signup is switched off on this site and is the wrong shape anyway:
	it asks for an email and a name, which is less than we already hold. By this point
	the mobile number is verified, the details are on a Loan Lead, and the borrower is
	choosing their own password in the same request -- so the session is opened here
	rather than making them go round to /login and type it again.

	Written with ignore_permissions throughout because the caller is a guest. What
	keeps that narrow is the token: it names one lead, it is spent once the account
	exists, and every value written comes off that lead rather than out of the request.
	"""
	assert_public_apply_enabled()

	# Read once: the writes below leave form_dict without it by the time it is spent.
	token = clean(frappe.form_dict.get("token"))
	lead_name = lead_for_account(token)

	# Not run through clean(): stripping a password would change it silently, and
	# leading or trailing spaces are the borrower's to choose.
	password = frappe.form_dict.get("password") or ""
	if len(password) < MINIMUM_PASSWORD_LENGTH:
		frappe.throw(
			_("Please choose a password of at least {0} characters.").format(
				MINIMUM_PASSWORD_LENGTH
			),
			frappe.ValidationError,
		)
	if password != (frappe.form_dict.get("confirm_password") or ""):
		frappe.throw(_("The two passwords do not match."), frappe.ValidationError)

	lead = frappe.db.get_value(
		"Loan Lead",
		lead_name,
		["applicant_name", "company_name", "applicant_type", "email", "mobile_number"],
		as_dict=True,
	)

	if frappe.db.exists("User", lead.email):
		frappe.throw(
			_("You already have an account. Please log in instead."), frappe.ValidationError
		)

	# Elevated deliberately, and only around these four writes. ignore_permissions is
	# not enough on its own: erpnext's Customer.on_update reaches a whitelisted API
	# that re-checks permissions whatever the caller passed, so a guest cannot save a
	# Customer at all. What keeps the elevation narrow is the token -- it names one
	# lead, it is spent on use, and every value below comes off that lead rather than
	# out of the request.
	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		user = frappe.new_doc("User")
		user.update(
			{
				"email": lead.email,
				"first_name": lead.company_name or lead.applicant_name,
				"mobile_no": lead.mobile_number,
				"user_type": "Website User",
				"send_welcome_email": 0,
				# Checked against the site's password policy on insert, so a weak one
				# is refused here rather than quietly accepted.
				"new_password": password,
			}
		)
		user.insert(ignore_permissions=True)
		user.add_roles("Customer")

		# A returning borrower keeps the customer record they already have, so their
		# earlier loans stay visible from the new login rather than sitting under a
		# duplicate nobody is joined to.
		customer = customer_for_applicant(
			lead.company_name or lead.applicant_name,
			lead.applicant_type,
			lead.email,
			lead.mobile_number,
		)
		link_portal_user(customer, user.name)
		# Last, so a password the policy refused above leaves the token for the retry.
		spend_account_token(token)
	finally:
		frappe.set_user(caller)

	# The borrower proved the number by OTP and chose this password a moment ago, so
	# there is nothing further to prove by sending them to the login page.
	#
	# login_manager exists only inside a web request. Called from a test or the
	# console there is no session to open, and the account has been made either way.
	if getattr(frappe.local, "login_manager", None):
		frappe.local.login_manager.login_as(user.name)

	return {
		"headline": _("Your account is ready"),
		"message": _("You are signed in as {0}.").format(user.name),
		"offer": [],
		"reference_note": "",
		"redirect": "/borrower-portal/overview",
	}


# --- a returning borrower -----------------------------------------------------------


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60)
def create_customer_lead() -> dict:
	"""A draft Loan Lead for a borrower who is already logged in.

	The same draft and the same rule steps as submit_lead. Only the identity differs:
	it comes off the borrower's Customer and User rather than out of the request, so
	there is no number to prove by OTP and no account to open afterwards.
	"""
	customer = read_own_customer()
	applicant = applicant_for(customer)
	data = read_loan_request(applicant["applicant_type"], applicant["company_name"])

	# ignore_permissions because Loan Lead grants create rights to System Manager only.
	# Every identity field is ours; the request picks only the product and the terms.
	lead = frappe.new_doc("Loan Lead")
	lead.update({**data, **applicant, "customer": customer, "lead_source": LEAD_SOURCE})
	lead.insert(ignore_permissions=True)

	settle_lead(lead.name, applicant["mobile_number"])
	lead.reload()

	return present_offer(lead)


def read_own_customer() -> str:
	"""The Customer the lead is for, which must be one of this login's own.

	A login can hold several -- a person and their company -- so the page names one.
	With only one there is nothing to choose.
	"""
	customers = get_portal_customers()
	asked = clean(frappe.form_dict.get("customer"))

	if not asked and len(customers) == 1:
		return customers[0]

	if asked not in customers:
		frappe.throw(_("Please choose who the loan is for."), frappe.ValidationError)

	return asked


def applicant_for(customer: str) -> dict:
	"""The lead's identity fields, read off records we hold rather than the request."""
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
		# A company's lead names the person asking, and the company separately.
		"applicant_name": user.full_name if business else record.customer_name,
		"company_name": record.customer_name if business else None,
		# The login's own address, so leads_for_login lists this lead with the rest.
		"email": user.email,
		"mobile_number": record.mobile_no or user.mobile_no or "",
	}


@frappe.whitelist()
def get_new_application_page() -> dict:
	"""The form a logged-in borrower applies with: who they are, and what is on offer.

	Every customer behind the login comes with what we already hold on it, so the page
	shows those details instead of asking for them, and switching between a person and
	their company needs no second request.
	"""
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
	"""One customer the borrower may apply as, with what the form shows and prefills."""
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
	"""What the borrower told us last time, so a second application starts filled in.

	A lead joined to this customer first. Failing that, a guest enquiry under the login's
	email -- which is how a borrower's first application arrived -- but only for the same
	kind of applicant, so a company never inherits the owner's date of birth.
	"""
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

	# A tax id is a PAN only when it is a PAN's length; a GSTIN is longer.
	tax_id = frappe.db.get_value("Customer", customer, "tax_id") or ""

	return {
		"income": flt(lead.income) or "",
		"employment_type": lead.employment_type or "",
		"date_of_birth": str(lead.date_of_birth or ""),
		"pan": lead.pan or (tax_id if len(tax_id) == PAN_LENGTH else ""),
		"proposed_tenure": cint(lead.proposed_tenure) or "",
	}


# --- the tracker --------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
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

	# Stored with a country code, but nobody types their own that way.
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

	# One refusal for a wrong reference, a wrong mobile, and a reference that was never
	# ours. Distinguishing them would turn this into a reference-number oracle.
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
	"""The tracker as a list of steps, so a longer workflow changes this and nothing else.

	PORTAL_PLAN.md section 6.6 asks for exactly one function to own these. When Module A
	reshapes the application workflow, the extra stages are added here and every page
	that draws a tracker picks them up.

	A step's `state` is "done", "now", "todo" or "stopped", and the page draws the dot
	for it -- a tick, a ring, an empty circle, a cross.
	"""
	declined = lead.prequalification_status == "Not Pre-Qualified"
	qualified = lead.prequalification_status == "Pre-Qualified"

	def as_step(title: str, note: str, state: str) -> dict:
		return {"title": title, "note": note, "state": state}

	steps = [
		as_step(_("Enquiry sent"), _("We have your details and your number is confirmed."), "done")
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
