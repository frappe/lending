# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import set_request
from frappe.website.serve import get_response

from lending.portal.login import (
	DEFAULT_REDIRECT,
	get_login_page,
	portal_redirect,
	send_login_code,
	verify_login_code,
)
from lending.tests.test_portal import make_website_user, set_portal_switches
from lending.tests.utils import LendingTestSuite

BORROWER = "_test-portal-login@example.com"
STRANGER = "_test-portal-nobody@example.com"


def login_response(url):
	path, _, query = url.partition("?")
	set_request(method="GET", path=path, query_string=query)
	return get_response()


def setUpModule():
	set_portal_switches(1, 1)
	frappe.db.commit()  # nosemgrep


class TestPortalLogin(LendingTestSuite):
	# Rate limits are inert here: frappe's decorator returns early without an HTTP request.

	def setUp(self):
		self.request = getattr(frappe.local, "request", None)
		make_website_user(BORROWER)
		frappe.set_user("Guest")
		frappe.local.login_manager = MagicMock()

	def tearDown(self):
		# login_response fakes an HTTP request; left in place, later modules run as if inside one.
		frappe.local.request = self.request
		frappe.set_user("Administrator")
		del frappe.local.login_manager
		super().tearDown()

	def test_a_code_goes_only_to_a_borrower(self):
		with patch("lending.portal.login.telephony_otp") as telephony:
			known = send_login_code(BORROWER)
			unknown = send_login_code(STRANGER)
			telephony.return_value.send_otp.assert_called_once()

		self.assertTrue(known["sent"])
		self.assertFalse(unknown["sent"])
		self.assertEqual(unknown["apply_url"], "/apply")

	def test_no_apply_link_when_public_apply_is_off(self):
		set_portal_switches(1, 0)
		self.addCleanup(set_portal_switches, 1, 1)

		with patch("lending.portal.login.telephony_otp"):
			result = send_login_code(STRANGER)

		self.assertFalse(result["sent"])
		self.assertEqual(result["apply_url"], "")

	def test_desk_users_cannot_log_in_by_code(self):
		desk_email = frappe.db.get_value("User", "Administrator", "email")
		with patch("lending.portal.login.telephony_otp") as telephony:
			send_login_code(desk_email)
			result = verify_login_code(desk_email, "123456")
			telephony.return_value.send_otp.assert_not_called()
			telephony.return_value.verify_otp.assert_not_called()

		self.assertFalse(result["verified"])
		frappe.local.login_manager.login_as.assert_not_called()

	def test_a_right_code_logs_the_borrower_in(self):
		with patch("lending.portal.login.telephony_otp") as telephony:
			telephony.return_value.verify_otp.return_value = {"verified": True}
			result = verify_login_code(BORROWER.upper(), "123456", "/borrower-portal/loans")

		self.assertEqual(result, {"verified": True, "redirect_to": "/borrower-portal/loans"})
		frappe.local.login_manager.login_as.assert_called_once_with(BORROWER)

	def test_a_wrong_code_returns_rather_than_raises(self):
		with patch("lending.portal.login.telephony_otp") as telephony:
			telephony.return_value.verify_otp.return_value = {"verified": False}
			result = verify_login_code(BORROWER, "000000")

		self.assertFalse(result["verified"])
		frappe.local.login_manager.login_as.assert_not_called()

	def test_a_bad_email_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			send_login_code("not-an-email")

	def test_redirects_stay_on_the_portal(self):
		self.assertEqual(portal_redirect("/borrower-portal/loan/L-1"), "/borrower-portal/loan/L-1")
		for target in ("https://evil.example/x", "//evil.example", "/desk", "", None):
			self.assertEqual(portal_redirect(target), DEFAULT_REDIRECT)

	def test_studio_login_goes_to_the_portal_page(self):
		# A plain /login first: it must not switch the redirect off for the next request.
		self.assertEqual(login_response("/login").status_code, 200)

		response = login_response("/login?redirect-to=%2Fborrower-portal%2Floans")
		self.assertEqual(response.status_code, 302)
		self.assertEqual(
			response.headers["Location"], "/borrower-portal/login?redirect-to=%2Fborrower-portal%2Floans"
		)

		self.assertEqual(login_response("/login?redirect-to=/desk").status_code, 200)

	def test_google_shows_only_when_configured(self):
		self.assertFalse(frappe.db.exists("Social Login Key", "google"))
		self.assertEqual(get_login_page()["google_url"], "")
