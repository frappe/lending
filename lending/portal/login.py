# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import validate_email_address
from frappe.utils.oauth import get_oauth2_authorize_url, get_oauth_keys
from frappe.utils.password import get_decrypted_password
from frappe.website.page_renderers.redirect_page import RedirectPage

from lending.portal.core import assert_portal_enabled, brand_payload, clean

LOGIN_CHANNEL = "Email"
LOGIN_PURPOSE = "Portal Login"

PORTAL_PREFIX = "/borrower-portal/"
PORTAL_LOGIN = "/borrower-portal/login"
DEFAULT_REDIRECT = "/borrower-portal/overview"

GOOGLE = "google"


class PortalLoginRedirect(RedirectPage):
	# Not website_redirects: Frappe caches those by path alone, so one plain /login switches the rule off.
	def __init__(self, path, http_status_code=None):
		super().__init__(path, 302)

	def can_render(self):
		redirect_to = frappe.local.request.args.get("redirect-to")
		return self.path == "login" and clean(redirect_to).startswith(PORTAL_PREFIX)

	def render(self):
		query = frappe.safe_decode(frappe.local.request.query_string)
		frappe.flags.redirect_location = f"{PORTAL_LOGIN}?{query}"
		return super().render()


@frappe.whitelist(allow_guest=True)  # nosemgrep
def get_login_page(redirect_to: str | None = None) -> dict:
	assert_portal_enabled()

	brand = brand_payload()
	public_apply = frappe.db.get_single_value("Lending Settings", "enable_public_apply")

	return {
		**brand,
		"heading": _("Log in to {0}").format(brand["brand_name"]),
		"intro": _("View your loans, repayments and statements."),
		"code_heading": _("Check your email"),
		"google_url": google_url(portal_redirect(redirect_to)),
		"show_signup": 1 if public_apply else 0,
	}


def portal_redirect(redirect_to: str | None) -> str:
	# Only portal paths, so the page can't be used to bounce a borrower off-site.
	path = clean(redirect_to)
	return path if path.startswith(PORTAL_PREFIX) else DEFAULT_REDIRECT


def google_url(redirect_to: str) -> str:
	if not frappe.db.get_value("Social Login Key", GOOGLE, "enable_social_login"):
		return ""
	if not get_decrypted_password("Social Login Key", GOOGLE, "client_secret", raise_exception=False):
		return ""
	if not get_oauth_keys(GOOGLE):
		return ""

	return get_oauth2_authorize_url(GOOGLE, redirect_to)


def portal_user(email: str) -> str | None:
	# Website users only: logging in by email code skips a desk user's password and 2FA.
	return frappe.db.get_value(
		"User", {"email": email, "enabled": 1, "user_type": "Website User"}, "name"
	)


def login_email(email) -> str:
	email = clean(email).lower()
	if not email or not validate_email_address(email):
		frappe.throw(_("Please enter a valid email address."), frappe.ValidationError)

	return email


def telephony_otp():
	if "telephony" not in frappe.get_installed_apps():
		frappe.throw(_("Email login is not switched on. Please try again later."))

	from telephony import otp

	return otp


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=10, seconds=60 * 60, ip_based=True)
def send_login_code(email: str) -> dict:
	assert_portal_enabled()
	email = login_email(email)
	otp = telephony_otp()

	if not portal_user(email):
		return no_account(email)

	otp.send_otp(email, LOGIN_CHANNEL, purpose=LOGIN_PURPOSE)

	return {
		"sent": True,
		"message": _("We sent a login code to {0}. It expires in {1} minutes.").format(
			email, code_expiry_minutes()
		),
		"hint": _("Not in your inbox? Check your spam folder."),
	}


def no_account(email: str) -> dict:
	if not frappe.db.get_single_value("Lending Settings", "enable_public_apply"):
		return {
			"sent": False,
			"message": _("We couldn't find an account for {0}. Please contact us for help.").format(email),
			"apply_url": "",
		}

	return {
		"sent": False,
		"message": _("We couldn't find an account for {0}. Please apply for a loan.").format(email),
		"apply_url": "/apply",
	}


def code_expiry_minutes() -> int:
	# TP OTP Settings ships with telephony, which lending does not require.
	seconds = 600
	if "telephony" in frappe.get_installed_apps():
		seconds = frappe.db.get_single_value("TP OTP Settings", "otp_expiry_in_seconds") or seconds

	return max(1, seconds // 60)


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=20, seconds=60 * 60, ip_based=True)
def verify_login_code(email: str, otp: str, redirect_to: str | None = None) -> dict:
	assert_portal_enabled()
	email = login_email(email)
	code = clean(otp)

	if not code:
		frappe.throw(_("Please enter the code we sent you."), frappe.ValidationError)

	user = portal_user(email)
	# Don't raise on failure: it would roll back the attempt telephony just recorded.
	result = user and telephony_otp().verify_otp(email, LOGIN_CHANNEL, code, purpose=LOGIN_PURPOSE)

	if not (result and result.get("verified")):
		return {"verified": False, "message": _("That code is wrong or has expired.")}

	frappe.local.login_manager.login_as(user)

	return {"verified": True, "redirect_to": portal_redirect(redirect_to)}
