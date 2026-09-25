# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Who may see what on the borrower portal, and who may write what.

PORTAL_PLAN.md section 8 says to treat every security rule as a test rather than as a
comment. These are those tests. They are about who may see what, not about arithmetic:
each one puts a real borrower in the session and asks the portal for a record that
belongs to somebody else.

Two of them are worth more than the rest.

test_a_missing_loan_and_another_borrowers_loan_are_indistinguishable is the one that
stops the portal becoming a lookup service. If "not yours" and "no such loan" read
differently, anyone can walk the loan numbering and learn which ones exist.

test_one_login_can_hold_several_customers guards the opposite mistake. Real data on
this bench has one email against three Customer records, so a helper that returns a
single customer would silently hide a borrower's own loans from them.

The later classes cover the writes: the public apply funnel, which creates rows with
no login at all, and the two borrower writes, which must reach the borrower's own
records and nothing beside them.
"""

import inspect
import json
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_years, getdate, nowdate
from frappe.utils.safe_exec import is_safe_exec_enabled

from lending.loan_management.doctype.lending_settings.lending_settings import (
	APPLY_ROUTE,
	portal_app,
	sync_portal_pages,
)
from lending.loan_origination.doctype.loan_lead.test_loan_lead import activate_loan_lead_workflow
from lending.portal.accounts import customer_for_email
from lending.portal.applications import (
	default_application,
	get_application_detail,
	get_document_choices,
	open_lead,
	upload_document,
)
from lending.portal.apply import (
	confirm_mobile_code,
	create_account,
	get_apply_page,
	get_track_page,
	read_product,
	send_mobile_code,
	submit_lead,
	track_application,
)
from lending.portal.brand import brand_style, brand_tokens, channels, contrast
from lending.portal.core import (
	CHOSEN_LOAN_KEY,
	DEFAULT_BRAND_NAME,
	PORTAL_ROUTE_PREFIX,
	REPAYMENTS_ROUTE,
	account_status,
	application_lead,
	assert_owns,
	brand_name,
	brand_payload,
	build_summary,
	copyright_note,
	days_ago,
	footer_links,
	get_dashboard,
	get_portal_customers,
	leads_for_login,
	money,
	name_once,
	nav_items,
	next_action,
	shell_payload,
	standing_line,
	waiting_on_borrower,
)
from lending.portal.loans import default_loan, get_loan_detail, request_disbursement
from lending.portal.notifications import (
	ATTENTION_LIMIT,
	READ_KEY,
	activity_rows,
	attention_rows,
	get_notifications,
	mark_all_as_read,
	read_keys,
	row_key,
)
from lending.portal.profile import get_profile_page, save_profile
from lending.portal.search import RESULT_LIMIT, find, results_note
from lending.portal.statement import owned_loans
from lending.portal.switcher import choose_account, get_accounts_page
from lending.tests.test_utils import (
	create_loan,
	create_loan_accounts,
	create_loan_product,
	set_loan_accrual_frequency,
	set_loan_settings_in_company,
	setup_loan_demand_offset_order,
)
from lending.tests.utils import LendingTestSuite

ALPHA_USER = "portal-alpha@example.com"
BETA_USER = "portal-beta@example.com"

# Alpha holds two customer records on purpose. One login to many customers is the
# real shape of the data, not an edge case.
ALPHA_CUSTOMER = "_Test Portal Alpha"
ALPHA_OTHER_CUSTOMER = "_Test Portal Alpha Second"
BETA_CUSTOMER = "_Test Portal Beta"

# A borrower who only ever holds one loan, for the account switch.
SINGLE_USER = "portal-single@example.com"
SINGLE_CUSTOMER = "_Test Portal Single"

# Used only by the shared-record test, which pins a Contact onto its customer. That
# is a lasting change, and this database is not rolled back between runs, so it gets
# a customer of its own rather than disturbing the one every other test edits.
SHARED_CUSTOMER = "_Test Portal Alpha Shared"

PRODUCT = "Personal Loan"

# National number only. The portal adds the country code a Phone field needs, and a
# visitor typing their own is exactly what the code under test has to cope with.
MOBILE = "9812345678"

# Fresh emails for the sign-up tests, which create real Users and delete them again.
PERSON_EMAIL = "_test-portal-person@example.com"
COMPANY_EMAIL = "_test-portal-company@example.com"


def set_portal_switches(portal: int, public_apply: int):
	"""Drive the two Lending Settings switches, the way saving the form would.

	sync_portal_pages is what Lending Settings.on_update runs, and it is half of what
	the switch does: the data layer refuses, and the pages stop being routed. Setting
	the values without it would test only the half that raises.
	"""
	frappe.db.set_single_value(
		"Lending Settings",
		{"enable_borrower_portal": portal, "enable_public_apply": public_apply},
	)
	sync_portal_pages()


def published_portal_routes() -> set[str]:
	"""The routes the portal actually serves, which is what the switches govern.

	Read off the pages rather than off the settings: a switch that flipped a field and
	left the pages published would pass a test of the field and serve the portal anyway.
	"""
	return set(
		frappe.get_all(
			"Studio Page",
			filters={"studio_app": portal_app(), "published": 1},
			pluck="route",
		)
	)


def show_product_on_portal(product: str, shown: int):
	frappe.db.set_value("Loan Product", product, "show_on_portal", shown)


def offer_product_to(product: str, applicant_type: str):
	frappe.db.set_value("Loan Product", product, "portal_applicant_type", applicant_type)


def offered_products(applicant_type: str) -> list[str]:
	return [row["value"] for row in get_apply_page()["products"][applicant_type]]


# Everything a lender may set about how the portal looks. Cleared between tests, so
# one test's red portal is not the next test's starting point.
BRAND_FIELDS = (
	"portal_brand_name",
	"portal_logo",
	"portal_support_email",
	"portal_primary_color",
	"portal_secondary_color",
)


def set_branding(**values):
	"""Fill in the Borrower Portal section, the way saving the desk form would.

	Saved rather than written underneath, because Lending Settings.on_update is where
	the portal's pages are published or unpublished, and setting the fields directly
	would test the half of the mechanism that never reaches a borrower.
	"""
	settings = frappe.get_doc("Lending Settings")
	settings.update({field: values.get(field) for field in BRAND_FIELDS})
	settings.save()


def set_footer(notice=None, links=(), support=None):
	"""Fill in the Portal Footer section, links and all.

	Separate from set_branding because the links are a child table: update() would
	take a list of dicts, but appending row by row is what the desk grid does, and the
	idx these come out in is half of what the footer tests are about.
	"""
	settings = frappe.get_doc("Lending Settings")
	settings.portal_copyright = notice
	settings.portal_support_email = support
	settings.portal_footer_links = []
	for label, url in links:
		settings.append("portal_footer_links", {"link_label": label, "url": url})
	settings.save()


def setUpModule():
	"""Switch the portal on for the whole file.

	Both switches default to off, which is right for a real site: a portal is a public
	surface and should not appear because somebody ran an upgrade. Left off here it
	would turn every test in this file into a 404.
	"""
	set_portal_switches(1, 1)


def make_website_user(email: str) -> str:
	"""A borrower is a Website User with the Customer role, per PORTAL_PLAN.md 10."""
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "Website User",
			}
		)
		user.flags.ignore_permissions = True
		user.insert()

	# add_roles skips a role the user already holds, so this is safe to repeat.
	frappe.get_doc("User", email).add_roles("Customer")

	return email


def make_portal_customer(name: str, user: str) -> str:
	"""A Customer joined to a login through the Portal Users table.

	This join is what get_portal_customers reads. Creating the Customer without it
	is the bug PORTAL_STATUS.md section 5.1 describes, so the fixture makes the row
	explicitly rather than relying on anything to add it.
	"""
	if not frappe.db.exists("Customer", name):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Individual",
				"customer_group": "_Test Customer Group",
				"territory": "_Test Territory",
			}
		).insert(ignore_permissions=True)

	customer = frappe.get_doc("Customer", name)
	if not any(row.user == user for row in customer.portal_users):
		customer.append("portal_users", {"user": user})
		customer.save(ignore_permissions=True)

	return name


def make_submitted_loan(applicant: str):
	"""A submitted loan, because the portal's list filters on docstatus 1."""
	loan = create_loan(applicant, PRODUCT, 100000, "Repay Over Number of Periods", repayment_periods=12)
	loan.submit()

	return loan


def make_application(applicant: str) -> str:
	application = frappe.get_doc(
		{
			"doctype": "Loan Application",
			"applicant_type": "Customer",
			"applicant": applicant,
			"company": "_Test Company",
			"loan_product": PRODUCT,
			"loan_amount": 100000,
			"repayment_method": "Repay Over Number of Periods",
			"repayment_periods": 12,
			"applicant_email_address": "lending@example.com",
			"applicant_phone_number": "+91-9108273645",
		}
	)
	application.insert(ignore_permissions=True)

	return application.name


class TestPortalOwnership(LendingTestSuite):
	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		set_loan_accrual_frequency("Monthly")
		create_loan_product(
			PRODUCT,
			PRODUCT,
			500000,
			8.4,
			repayment_schedule_type="Monthly as per repayment start date",
		)
		show_product_on_portal(PRODUCT, 1)

		make_website_user(ALPHA_USER)
		make_website_user(BETA_USER)
		make_portal_customer(ALPHA_CUSTOMER, ALPHA_USER)
		make_portal_customer(ALPHA_OTHER_CUSTOMER, ALPHA_USER)
		make_portal_customer(BETA_CUSTOMER, BETA_USER)

		self.alpha_loan = make_submitted_loan(ALPHA_CUSTOMER).name
		self.beta_loan = make_submitted_loan(BETA_CUSTOMER).name
		self.beta_application = make_application(BETA_CUSTOMER)

		frappe.db.commit()  # nosemgrep

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.form_dict.pop("name", None)

	def as_alpha(self):
		frappe.set_user(ALPHA_USER)

	# --- who am I -------------------------------------------------------------------

	def test_portal_customers_are_scoped_to_the_login(self):
		self.as_alpha()
		customers = get_portal_customers()

		self.assertIn(ALPHA_CUSTOMER, customers)
		self.assertNotIn(BETA_CUSTOMER, customers)

	def test_one_login_can_hold_several_customers(self):
		self.as_alpha()
		customers = get_portal_customers()

		self.assertIn(ALPHA_CUSTOMER, customers)
		self.assertIn(ALPHA_OTHER_CUSTOMER, customers)

	def test_a_guest_cannot_reach_the_portal(self):
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			get_portal_customers()

	# --- lists ----------------------------------------------------------------------

	def test_the_default_loan_is_the_borrowers_own(self):
		self.as_alpha()

		applicant = frappe.db.get_value("Loan", default_loan(), "applicant")

		self.assertIn(applicant, get_portal_customers())

	def test_the_default_application_is_the_borrowers_own(self):
		self.as_alpha()

		self.assertNotEqual(default_application(), self.beta_application)
		self.assertTrue(default_application())

	# --- the guard itself -----------------------------------------------------------

	def test_assert_owns_returns_the_applicant_for_your_own_record(self):
		self.as_alpha()

		self.assertEqual(assert_owns("Loan", self.alpha_loan), ALPHA_CUSTOMER)

	def test_assert_owns_refuses_another_borrowers_record(self):
		self.as_alpha()

		with self.assertRaises(frappe.PermissionError):
			assert_owns("Loan", self.beta_loan)

	# --- detail pages ---------------------------------------------------------------

	def test_another_borrowers_loan_is_refused(self):
		self.as_alpha()
		frappe.form_dict["name"] = self.beta_loan

		with self.assertRaises(frappe.PermissionError):
			get_loan_detail()

	def test_your_own_loan_is_allowed(self):
		self.as_alpha()
		frappe.form_dict["name"] = self.alpha_loan

		self.assertEqual(get_loan_detail()["crumb"], PRODUCT)

	def test_another_borrowers_application_is_refused(self):
		self.as_alpha()
		frappe.form_dict["name"] = self.beta_application

		with self.assertRaises(frappe.PermissionError):
			get_application_detail()

	def test_an_application_detail_with_no_name_opens_the_newest(self):
		self.as_alpha()
		frappe.form_dict.pop("name", None)

		payload = get_application_detail()
		self.assertEqual(payload["product"], PRODUCT)
		self.assertIs(payload["has_application"], True)

	def test_a_borrower_with_no_application_gets_the_empty_state(self):
		self.as_alpha()
		frappe.form_dict.pop("name", None)

		with patch("lending.portal.applications.default_application", return_value=None):
			self.assertIs(get_application_detail()["has_application"], False)

	def test_a_loan_detail_with_no_name_opens_the_default_loan(self):
		self.as_alpha()
		frappe.form_dict.pop("name", None)

		self.assertEqual(get_loan_detail()["crumb"], PRODUCT)

	def test_a_missing_loan_and_another_borrowers_loan_are_indistinguishable(self):
		"""The refusal must not tell a stranger which loan numbers exist."""
		self.as_alpha()

		frappe.form_dict["name"] = self.beta_loan
		with self.assertRaises(frappe.PermissionError) as theirs:
			get_loan_detail()

		frappe.form_dict["name"] = "LOAN-DOES-NOT-EXIST"
		with self.assertRaises(frappe.PermissionError) as missing:
			get_loan_detail()

		self.assertEqual(str(theirs.exception), str(missing.exception))


class TestPortalGuestEndpoints(LendingTestSuite):
	"""The public front: what a stranger may do, and where they are stopped.

	These endpoints write rows without a login, so the tests are mostly about refusal.
	The rate limits that guard them in production are inert here -- frappe's decorator
	returns early when there is no HTTP request -- so nothing below is throttled.
	"""

	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		create_loan_product(
			PRODUCT,
			PRODUCT,
			500000,
			8.4,
			repayment_schedule_type="Monthly as per repayment start date",
		)
		show_product_on_portal(PRODUCT, 1)
		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()

	def submission(self, **overrides):
		frappe.local.form_dict = frappe._dict(
			{
				"applicant_name": "Test Applicant",
				"email": "applicant@example.com",
				"loan_product": PRODUCT,
				"loan_amount": 100000,
				**overrides,
			}
		)

	def mint_token(self, mobile=MOBILE):
		"""Walk step 2 with the SMS provider stubbed, and keep the token it returns."""
		frappe.local.form_dict = frappe._dict({"mobile_number": mobile, "otp": "123456"})
		with patch("lending.portal.apply.telephony_otp") as telephony:
			telephony.return_value.verify_otp.return_value = {"verified": True}
			result = confirm_mobile_code()

		return result["token"]

	# --- browsing -------------------------------------------------------------------

	def test_a_guest_can_read_the_apply_page(self):
		payload = get_apply_page()

		self.assertIn(PRODUCT, [row["value"] for row in payload["products"]["Individual"]])

	# --- verifying the number -------------------------------------------------------

	def test_a_code_is_sent_to_the_number_given(self):
		frappe.local.form_dict = frappe._dict({"mobile_number": MOBILE})
		with patch("lending.portal.apply.telephony_otp") as telephony:
			result = send_mobile_code()
			telephony.return_value.send_otp.assert_called_once()

		# Only the last two digits come back, so the page can confirm which number
		# it used without printing it.
		self.assertNotIn(MOBILE, result["message"])
		self.assertIn(MOBILE[-2:], result["message"])

	def test_a_number_that_is_not_a_number_is_refused(self):
		frappe.local.form_dict = frappe._dict({"mobile_number": "12"})

		with self.assertRaises(frappe.ValidationError):
			send_mobile_code()

	def test_a_wrong_code_hands_back_no_token(self):
		frappe.local.form_dict = frappe._dict({"mobile_number": MOBILE, "otp": "000000"})
		with patch("lending.portal.apply.telephony_otp") as telephony:
			telephony.return_value.verify_otp.return_value = {"verified": False}
			result = confirm_mobile_code()

		self.assertFalse(result["verified"])
		self.assertNotIn("token", result)

	# --- creating the lead ----------------------------------------------------------

	def test_a_lead_cannot_be_created_without_verifying_a_number(self):
		self.submission()

		with self.assertRaises(frappe.ValidationError):
			submit_lead()

	def test_a_token_we_never_issued_is_refused(self):
		self.submission(token="not-a-token-we-issued")

		with self.assertRaises(frappe.ValidationError):
			submit_lead()

	def test_a_verified_number_creates_a_draft_and_verified_lead(self):
		token = self.mint_token()
		self.submission(token=token, income=60000, pan="ABCDE1234F")
		result = submit_lead()

		lead = frappe.db.get_value(
			"Loan Lead",
			result["reference"],
			["mobile_number", "mobile_verification_status", "lead_source", "docstatus", "pan"],
			as_dict=True,
		)

		self.assertEqual(lead.mobile_number, f"+91{MOBILE}")
		# The status survives validate, which resets it on every save. If this fails,
		# mark_mobile_verified is writing too early again.
		self.assertEqual(lead.mobile_verification_status, "Verified")
		self.assertEqual(lead.lead_source, "Portal")
		self.assertEqual(lead.pan, "ABCDE1234F")
		# A submitted lead skips every rule step in the Loan Lead Workflow.
		self.assertEqual(lead.docstatus, 0)

	def test_a_token_works_once(self):
		token = self.mint_token()
		self.submission(token=token)
		submit_lead()

		self.submission(token=token)
		with self.assertRaises(frappe.ValidationError):
			submit_lead()

	def test_a_refused_submission_leaves_the_token_usable(self):
		token = self.mint_token()
		self.submission(token=token, email="")
		with self.assertRaises(frappe.ValidationError):
			submit_lead()

		self.submission(token=token)
		self.assertTrue(submit_lead()["reference"])

	def test_a_lead_that_fails_to_save_leaves_the_token_usable(self):
		token = self.mint_token()
		self.submission(token=token)
		with patch("frappe.model.document.Document.insert", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				submit_lead()

		self.submission(token=token)
		self.assertTrue(submit_lead()["reference"])

	def test_a_verification_survives_a_cache_clear(self):
		# A migrate or a DocType save clears the whole cache, mid-application or not.
		token = self.mint_token()
		frappe.clear_cache()

		self.submission(token=token)
		self.assertTrue(submit_lead()["reference"])

	def test_more_than_the_product_allows_is_refused(self):
		token = self.mint_token()
		self.submission(token=token, loan_amount=99999999)

		with self.assertRaises(frappe.ValidationError):
			submit_lead()

	def test_a_product_that_is_not_offered_is_refused(self):
		token = self.mint_token()
		self.submission(token=token, loan_product="No Such Product")

		with self.assertRaises(frappe.ValidationError):
			submit_lead()

	def test_an_applicant_who_is_too_young_is_refused(self):
		token = self.mint_token()
		self.submission(token=token, date_of_birth=add_years(nowdate(), -10))

		with self.assertRaises(frappe.ValidationError):
			submit_lead()

	# --- the workflow rules ---------------------------------------------------------

	def use_lead_workflow(self):
		if not frappe.db.exists("Workflow", "Loan Lead Workflow"):
			self.skipTest("requires the Loan Lead Workflow fixture")

		if not is_safe_exec_enabled():
			self.skipTest("Run Basic Rules runs Server Scripts, which need server_script_enabled")

		frappe.set_user("Administrator")
		activate_loan_lead_workflow(self)
		frappe.set_user("Guest")

	def test_a_portal_lead_runs_the_rule_steps_as_a_draft(self):
		self.use_lead_workflow()
		self.submission(token=self.mint_token(), date_of_birth=add_years(nowdate(), -30))

		lead = frappe.db.get_value(
			"Loan Lead", submit_lead()["reference"], ["docstatus", "workflow_state"], as_dict=True
		)

		self.assertEqual(lead.docstatus, 0)
		self.assertEqual(lead.workflow_state, "Pre-Qualified")
		self.assertEqual(frappe.session.user, "Guest")

	def test_a_rule_that_says_no_leaves_the_lead_at_incoming_with_a_note(self):
		self.use_lead_workflow()
		self.submission(token=self.mint_token(), date_of_birth=add_years(nowdate(), -30))

		def pre_qualify(doc):
			doc.db_set("prequalification_status", "Pre-Qualified")

		with (
			patch("lending.loan_origination.decisioning.run_pre_qualification_rules", pre_qualify),
			patch(
				"lending.loan_origination.decisioning.run_knockout_rules",
				side_effect=frappe.ValidationError("Knockout rules declined this applicant."),
			),
		):
			result = submit_lead()

		lead = frappe.db.get_value(
			"Loan Lead",
			result["reference"],
			["workflow_state", "prequalification_status", "mobile_verification_status"],
			as_dict=True,
		)

		# The knockout rules took back the pre-qualification, so the page must not show it.
		self.assertEqual(lead.workflow_state, "Incoming")
		self.assertFalse(lead.prequalification_status)
		self.assertEqual(result["headline"], "Thank you, we have your enquiry")
		self.assertEqual(lead.mobile_verification_status, "Verified")

		note = frappe.db.get_value(
			"Comment",
			{"reference_doctype": "Loan Lead", "reference_name": result["reference"]},
			"content",
		)
		self.assertIn("Run Knockout Rules", note)
		self.assertIn("Knockout rules declined", note)

	# --- tracking -------------------------------------------------------------------

	def test_tracking_needs_both_the_reference_and_the_mobile(self):
		frappe.local.form_dict = frappe._dict({"reference": "LN-LEAD-00001"})

		with self.assertRaises(frappe.ValidationError):
			track_application()

	def test_tracking_a_lead_returns_its_steps(self):
		token = self.mint_token()
		self.submission(token=token)
		reference = submit_lead()["reference"]

		frappe.local.form_dict = frappe._dict({"reference": reference, "mobile_number": MOBILE})
		payload = track_application()

		self.assertEqual(payload["reference"], reference)
		self.assertTrue(payload["steps"])

	def test_a_wrong_reference_and_a_wrong_mobile_give_the_same_refusal(self):
		"""Otherwise the tracker becomes a way to guess other people's references."""
		token = self.mint_token()
		self.submission(token=token)
		reference = submit_lead()["reference"]

		frappe.local.form_dict = frappe._dict({"reference": "LN-LEAD-99999", "mobile_number": MOBILE})
		with self.assertRaises(frappe.ValidationError) as unknown:
			track_application()

		frappe.local.form_dict = frappe._dict({"reference": reference, "mobile_number": "9000000001"})
		with self.assertRaises(frappe.ValidationError) as wrong_mobile:
			track_application()

		self.assertEqual(str(unknown.exception), str(wrong_mobile.exception))


class PortalPeople(LendingTestSuite):
	"""Two borrowers with customer records, and no loans. The writes need neither."""

	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		create_loan_product(
			PRODUCT,
			PRODUCT,
			500000,
			8.4,
			repayment_schedule_type="Monthly as per repayment start date",
		)
		show_product_on_portal(PRODUCT, 1)

		make_website_user(ALPHA_USER)
		make_website_user(BETA_USER)
		make_portal_customer(ALPHA_CUSTOMER, ALPHA_USER)
		make_portal_customer(ALPHA_OTHER_CUSTOMER, ALPHA_USER)
		make_portal_customer(SHARED_CUSTOMER, ALPHA_USER)
		make_portal_customer(BETA_CUSTOMER, BETA_USER)
		frappe.db.commit()  # nosemgrep

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()

	def as_alpha(self):
		frappe.set_user(ALPHA_USER)


class TestPortalProfileWrite(PortalPeople):
	def post(self, **fields):
		frappe.local.form_dict = frappe._dict({"customer": ALPHA_CUSTOMER, **fields})

	def test_correcting_another_borrowers_record_is_refused(self):
		self.as_alpha()
		self.post(customer=BETA_CUSTOMER, email="thief@example.com")

		with self.assertRaises(frappe.PermissionError):
			save_profile()

	def test_a_customer_that_does_not_exist_is_refused(self):
		self.as_alpha()
		self.post(customer="No Such Customer", email="someone@example.com")

		with self.assertRaises(frappe.PermissionError):
			save_profile()

	def test_contact_details_and_address_are_saved(self):
		self.as_alpha()
		self.post(
			email="alpha.saved@example.com",
			mobile="9812340001",
			address_line1="12 Hill Road",
			city="Mumbai",
			state="Maharashtra",
			pincode="400050",
		)
		save_profile()

		frappe.local.form_dict = frappe._dict({"customer": ALPHA_CUSTOMER})
		form = get_profile_page()

		self.assertEqual(form["form_email"], "alpha.saved@example.com")
		self.assertEqual(form["form_mobile"], "9812340001")
		self.assertEqual(form["form_city"], "Mumbai")
		# The page switches records from this map rather than asking again.
		self.assertEqual(form["forms"][ALPHA_CUSTOMER]["city"], "Mumbai")

	def test_a_landline_does_not_overwrite_the_mobile(self):
		"""Both live in phone_nos under different flags, so the write must not
		fall back to whichever row happens to be first."""
		self.as_alpha()
		self.post(email="alpha.saved@example.com", mobile="9812340002", phone="02212345678")
		save_profile()

		frappe.local.form_dict = frappe._dict({"customer": ALPHA_CUSTOMER})
		form = get_profile_page()

		self.assertEqual(form["form_mobile"], "9812340002")
		self.assertEqual(form["form_phone"], "02212345678")

	def test_an_invalid_email_is_refused(self):
		self.as_alpha()
		self.post(email="not-an-email")

		with self.assertRaises(frappe.ValidationError):
			save_profile()

	def test_a_record_shared_with_another_borrower_is_left_alone(self):
		"""A Contact linked to somebody else's customer must not be edited in place.

		Frappe makes one Contact per login and erpnext links it to each customer that
		login serves, so a shared record is ordinary. Editing one that also serves a
		stranger would change what that stranger sees.
		"""
		shared = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "_Test Shared Contact",
				"links": [
					{"link_doctype": "Customer", "link_name": SHARED_CUSTOMER},
					{"link_doctype": "Customer", "link_name": BETA_CUSTOMER},
				],
			}
		)
		shared.add_email("shared@example.com", is_primary=1)
		shared.insert(ignore_permissions=True)
		frappe.db.set_value("Customer", SHARED_CUSTOMER, "customer_primary_contact", shared.name)
		frappe.db.commit()  # nosemgrep

		self.as_alpha()
		self.post(customer=SHARED_CUSTOMER, email="alpha.private@example.com", mobile="9812340003")
		save_profile()

		self.assertEqual(
			frappe.db.get_value("Contact", shared.name, "email_id"), "shared@example.com"
		)

	def test_an_address_with_no_country_still_saves(self):
		"""Address.country is mandatory and india_compliance has its own rule about it,
		so a blank box must resolve to something rather than quoting either at the
		borrower."""
		self.as_alpha()
		self.post(
			email="alpha.saved@example.com",
			address_line1="9 Marine Drive",
			city="Mumbai",
			state="Maharashtra",
		)
		save_profile()

		frappe.local.form_dict = frappe._dict({"customer": ALPHA_CUSTOMER})

		self.assertTrue(get_profile_page()["form_country"])

	def test_a_country_we_do_not_recognise_is_refused(self):
		self.as_alpha()
		self.post(
			email="alpha.saved@example.com",
			address_line1="1 Nowhere",
			city="Nowhere",
			state="Nowhere",
			country="Freedonia",
		)

		with self.assertRaises(frappe.ValidationError):
			save_profile()

	def test_half_an_address_is_refused_in_our_own_words(self):
		self.as_alpha()
		self.post(email="alpha.saved@example.com", pincode="400050")

		with self.assertRaises(frappe.ValidationError) as refusal:
			save_profile()

		self.assertIn("city", str(refusal.exception).lower())

class TestPortalDocumentUpload(PortalPeople):
	def setUp(self):
		super().setUp()
		self.alpha_draft = make_application(ALPHA_CUSTOMER)
		self.beta_draft = make_application(BETA_CUSTOMER)
		if not frappe.db.exists("Loan Document Type", "_Test Payslip"):
			frappe.get_doc(
				{"doctype": "Loan Document Type", "loan_document_type": "_Test Payslip"}
			).insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep

	def post(self, **fields):
		frappe.local.form_dict = frappe._dict(
			{"application": self.alpha_draft, "document_type": "_Test Payslip", **fields}
		)

	def test_uploading_to_another_borrowers_application_is_refused(self):
		self.as_alpha()
		self.post(application=self.beta_draft)

		with self.assertRaises(frappe.PermissionError):
			upload_document()

	def test_uploading_without_naming_an_application_is_refused(self):
		self.as_alpha()
		self.post(application="")

		with self.assertRaises(frappe.PermissionError):
			upload_document()

	def test_an_unknown_document_type_is_refused(self):
		self.as_alpha()
		self.post(document_type="Not A Document Type")

		with self.assertRaises(frappe.ValidationError):
			upload_document()

	def test_uploading_to_a_submitted_application_is_refused(self):
		"""A submitted application is with our team; section 6.2 keeps the borrower out."""
		application = frappe.get_doc("Loan Application", self.alpha_draft)
		application.status = "Approved"
		application.submit()
		frappe.db.commit()  # nosemgrep

		self.as_alpha()
		self.post()

		with self.assertRaises(frappe.ValidationError):
			upload_document()

	def test_a_draft_of_your_own_gets_as_far_as_the_file(self):
		"""Everything ahead of the file passes, and the missing file is what stops it.

		There is no multipart request in a test, so this proves the guards let an owned
		draft through rather than proving a file lands.
		"""
		self.as_alpha()
		self.post()

		with self.assertRaises(frappe.ValidationError) as refusal:
			upload_document()

		self.assertIn("file", str(refusal.exception).lower())

	def test_only_draft_applications_are_offered(self):
		self.as_alpha()
		frappe.local.form_dict = frappe._dict()
		choices = get_document_choices()
		offered = [row["value"] for row in choices["application_options"]]

		self.assertIn(self.alpha_draft, offered)
		self.assertNotIn(self.beta_draft, offered)


class TestPortalSignUp(LendingTestSuite):
	"""Opening an account at the end of an application, and what it is joined to.

	This is the chain that used to be broken: a borrower could apply, but nothing
	created a login, nothing created a Customer they could be joined to, and nothing
	wrote the Customer.portal_users row every page reads. Each test below holds one
	link of it in place.
	"""

	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		create_loan_product(
			PRODUCT,
			PRODUCT,
			500000,
			8.4,
			repayment_schedule_type="Monthly as per repayment start date",
		)
		show_product_on_portal(PRODUCT, 1)
		for email in (PERSON_EMAIL, COMPANY_EMAIL):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep

		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()

	def apply_as(self, email, mobile, **overrides):
		"""Walk steps 2 and 3 with the SMS provider stubbed, and return the offer."""
		frappe.local.form_dict = frappe._dict({"mobile_number": mobile, "otp": "123456"})
		with patch("lending.portal.apply.telephony_otp") as telephony:
			telephony.return_value.verify_otp.return_value = {"verified": True}
			token = confirm_mobile_code()["token"]

		frappe.local.form_dict = frappe._dict(
			{
				"token": token,
				"applicant_name": "Test Applicant",
				"email": email,
				"loan_product": PRODUCT,
				"loan_amount": 100000,
				**overrides,
			}
		)

		return submit_lead()

	def open_account(self, offer, password="Kh8!zQr2wLp5", confirm_password=None):
		frappe.local.form_dict = frappe._dict(
			{
				"token": offer["account_token"],
				"password": password,
				"confirm_password": password if confirm_password is None else confirm_password,
			}
		)

		return create_account()

	# --- person or company ----------------------------------------------------------

	def test_a_company_is_recorded_as_one(self):
		offer = self.apply_as(
			COMPANY_EMAIL,
			"9812340101",
			applicant_type="Business",
			company_name="Test Traders Pvt Ltd",
			# Sent, and dropped, because neither belongs to a company.
			date_of_birth="1990-01-01",
			employment_type="Salaried",
		)
		lead = frappe.db.get_value(
			"Loan Lead",
			offer["reference"],
			["applicant_type", "company_name", "date_of_birth", "employment_type"],
			as_dict=True,
		)

		self.assertEqual(lead.applicant_type, "Business")
		self.assertEqual(lead.company_name, "Test Traders Pvt Ltd")
		self.assertIsNone(lead.date_of_birth)
		# Empty rather than None: frappe fills a None Select with its first option,
		# which would record every company as Salaried.
		self.assertEqual(lead.employment_type, "")

	def test_a_company_must_give_its_name(self):
		with self.assertRaises(frappe.ValidationError):
			self.apply_as(COMPANY_EMAIL, "9812340102", applicant_type="Business")

	def test_a_company_account_is_a_company_customer(self):
		offer = self.apply_as(
			COMPANY_EMAIL, "9812340103", applicant_type="Business", company_name="Test Traders Pvt Ltd"
		)
		self.open_account(offer)

		customer = frappe.db.get_value(
			"Customer",
			customer_for_email(COMPANY_EMAIL),
			["customer_name", "customer_type"],
			as_dict=True,
		)

		self.assertEqual(customer.customer_name, "Test Traders Pvt Ltd")
		self.assertEqual(customer.customer_type, "Company")

	# --- the account ----------------------------------------------------------------

	def test_an_account_is_opened_and_joined_to_a_customer(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340104")
		self.open_account(offer)

		self.assertTrue(frappe.db.exists("User", PERSON_EMAIL))
		self.assertIn("Customer", frappe.get_roles(PERSON_EMAIL))

		customer = customer_for_email(PERSON_EMAIL)
		self.assertTrue(customer)

		# The row every borrower page reads. Without it the portal is silently empty.
		joined = [row.user for row in frappe.get_doc("Customer", customer).portal_users]
		self.assertIn(PERSON_EMAIL, joined)

	def test_the_new_borrower_sees_their_own_enquiry(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340105")
		self.open_account(offer)

		frappe.set_user(PERSON_EMAIL)
		frappe.local.form_dict = frappe._dict()

		self.assertIn(offer["reference"], [row.name for row in leads_for_login()])

	def test_the_application_page_follows_an_enquiry_before_it_is_an_application(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340107")
		self.open_account(offer)

		frappe.set_user(PERSON_EMAIL)
		frappe.local.form_dict = frappe._dict()

		# The newest enquiry, not whatever else this address raised in earlier runs.
		lead = leads_for_login()[0]
		self.assertEqual(lead.name, offer["reference"])

		with patch("lending.portal.applications.default_application", return_value=None):
			payload = get_application_detail()

		self.assertIs(payload["has_application"], True)
		self.assertEqual(payload["reference"], "Enquiry {0}".format(offer["reference"]))
		self.assertEqual(payload["steps"][0]["code"], "done")

	def test_a_converted_enquiry_gives_way_to_its_application(self):
		lead = frappe._dict(name="LN-LEAD-CONVERTED")

		with patch("lending.portal.applications.leads_for_login", return_value=[lead]):
			self.assertEqual(open_lead(), lead)

			with patch("frappe.get_all", return_value=[lead.name]):
				self.assertIsNone(open_lead())

	def test_an_account_needs_a_token(self):
		self.apply_as(PERSON_EMAIL, "9812340106")
		frappe.local.form_dict = frappe._dict({"password": "Kh8!zQr2wLp5"})

		with self.assertRaises(frappe.ValidationError):
			create_account()

	def test_an_account_token_works_once(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340107")
		self.open_account(offer)

		with self.assertRaises(frappe.ValidationError):
			self.open_account(offer)

	def test_a_second_account_for_the_same_email_is_refused(self):
		self.open_account(self.apply_as(PERSON_EMAIL, "9812340108"))
		second = self.apply_as(PERSON_EMAIL, "9812340109")

		with self.assertRaises(frappe.ValidationError):
			self.open_account(second)

	def test_a_one_character_password_is_refused(self):
		"""The site's own password policy let this through, so the endpoint has a
		floor of its own rather than trusting a setting."""
		offer = self.apply_as(PERSON_EMAIL, "9812340110")

		with self.assertRaises(frappe.ValidationError):
			self.open_account(offer, password="a")

		self.assertFalse(frappe.db.exists("User", PERSON_EMAIL))

	def test_a_password_that_does_not_match_its_confirmation_is_refused(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340113")

		with self.assertRaises(frappe.ValidationError):
			self.open_account(offer, confirm_password="Kh8!zQr2wLp6")

		self.assertFalse(frappe.db.exists("User", PERSON_EMAIL))

	def test_a_refused_password_can_be_tried_again(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340112")
		with self.assertRaises(frappe.ValidationError):
			self.open_account(offer, password="a")

		self.open_account(offer)
		self.assertTrue(frappe.db.exists("User", PERSON_EMAIL))

	# --- the join survives conversion -----------------------------------------------

	def test_converting_a_lead_reuses_the_borrowers_customer(self):
		"""Otherwise the borrower ends up with two Customer records, their login
		joined to the first, and the loan on the second one invisible to them."""
		self.open_account(self.apply_as(PERSON_EMAIL, "9812340111"))
		customer = customer_for_email(PERSON_EMAIL)

		frappe.set_user("Administrator")
		before = frappe.db.count("Customer")
		application = frappe.get_doc(
			{
				"doctype": "Loan Application",
				"applicant_type": "Customer",
				"company": "_Test Company",
				"loan_product": PRODUCT,
				"loan_amount": 100000,
				"repayment_method": "Repay Over Number of Periods",
				"repayment_periods": 12,
				"applicant_name": "Test Applicant",
				"applicant_email_address": PERSON_EMAIL,
				"applicant_phone_number": "+919812340111",
			}
		)
		application.insert(ignore_permissions=True)

		self.assertEqual(application.applicant, customer)
		self.assertEqual(frappe.db.count("Customer"), before)


class TestPortalSwitches(LendingTestSuite):
	"""The three switches a lender uses to decide what the portal serves.

	Every refusal here has to be frappe.PageDoesNotExistError and not PermissionError.
	website/serve.py renders the first as 404 and the second as "not permitted", and a
	lender who switched the portal off wants it gone rather than hidden behind a refusal
	that confirms it is there.

	The signed-in checks run as Administrator on purpose. The switch is read before the
	guest check, so a real borrower is not needed to prove it fires, and using one would
	tie these tests to the fixtures of another class.
	"""

	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		create_loan_product(
			PRODUCT,
			PRODUCT,
			500000,
			8.4,
			repayment_schedule_type="Monthly as per repayment start date",
		)
		show_product_on_portal(PRODUCT, 1)
		frappe.local.form_dict = frappe._dict()

	def tearDown(self):
		set_portal_switches(1, 1)
		show_product_on_portal(PRODUCT, 1)
		offer_product_to(PRODUCT, "")
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()

	def test_portal_off_hides_every_signed_in_page(self):
		set_portal_switches(0, 0)

		self.assertRaises(frappe.PageDoesNotExistError, get_portal_customers)

	def test_portal_off_hides_the_public_pages(self):
		set_portal_switches(0, 0)

		self.assertRaises(frappe.PageDoesNotExistError, get_apply_page)
		self.assertRaises(frappe.PageDoesNotExistError, get_track_page)

	def test_portal_off_closes_the_endpoints_that_write(self):
		"""The switch has to stop the writes, not only the pages that lead to them."""
		set_portal_switches(0, 0)
		frappe.set_user("Guest")

		self.assertRaises(frappe.PageDoesNotExistError, send_mobile_code)
		self.assertRaises(frappe.PageDoesNotExistError, submit_lead)
		self.assertRaises(frappe.PageDoesNotExistError, create_account)

	def test_public_apply_off_leaves_the_signed_in_portal_serving(self):
		"""A lender whose sales team keys leads in the desk wants exactly this."""
		set_portal_switches(1, 0)

		self.assertRaises(frappe.PageDoesNotExistError, get_apply_page)
		self.assertRaises(frappe.PageDoesNotExistError, submit_lead)

		# The tracker follows the portal switch alone: a lead raised by a sales rep
		# still deserves a tracker.
		self.assertTrue(get_track_page()["heading"])

		# And a borrower who already has a login is untouched.
		self.assertIsInstance(get_portal_customers(), list)

	def test_a_product_not_shown_on_the_portal_is_not_offered(self):
		show_product_on_portal(PRODUCT, 0)

		self.assertNotIn(PRODUCT, offered_products("Individual"))
		self.assertNotIn(PRODUCT, offered_products("Business"))

	def test_a_product_not_shown_on_the_portal_cannot_be_applied_for(self):
		"""Filtering the list alone would leave it one guessed name away."""
		show_product_on_portal(PRODUCT, 0)

		self.assertRaises(frappe.ValidationError, read_product, PRODUCT, 100000)

	def test_a_product_shown_on_the_portal_is_offered_and_accepted(self):
		# No applicant type set on the product means both are offered it.
		self.assertIn(PRODUCT, offered_products("Individual"))
		self.assertIn(PRODUCT, offered_products("Business"))
		self.assertEqual(read_product(PRODUCT, 100000)["name"], PRODUCT)
		self.assertEqual(read_product(PRODUCT, 100000, "Business")["name"], PRODUCT)

	def test_a_business_product_is_offered_to_companies_alone(self):
		offer_product_to(PRODUCT, "Business")

		self.assertIn(PRODUCT, offered_products("Business"))
		self.assertNotIn(PRODUCT, offered_products("Individual"))

	def test_a_person_cannot_apply_for_a_business_product(self):
		"""Filtering the list alone would leave it one guessed name away."""
		offer_product_to(PRODUCT, "Business")

		self.assertRaises(frappe.ValidationError, read_product, PRODUCT, 100000, "Individual")
		self.assertEqual(read_product(PRODUCT, 100000, "Business")["name"], PRODUCT)

	def test_portal_off_takes_every_page_out_of_the_route_table(self):
		"""The data layer refusing is not enough on its own.

		A refusal raised while a page renders comes back as the 404 page with a 200
		status. Only an unresolved route gives a real 404, and a Studio App is served
		at all only while it has a published page -- so unpublishing them takes the
		whole portal off the website rather than leaving a shell that says it is shut.
		"""
		set_portal_switches(0, 0)

		self.assertEqual(published_portal_routes(), set())

	def test_public_apply_off_takes_only_the_apply_page_out(self):
		"""The tracker is not the form. Somebody who already applied while it was open
		still has a reference number to look up, so closing the form does not close the
		page that answers for it."""
		set_portal_switches(1, 0)
		routes = published_portal_routes()

		self.assertNotIn(APPLY_ROUTE, routes)
		self.assertIn("/track", routes)
		self.assertIn("/overview", routes)

	def test_switching_the_portal_back_on_restores_every_page(self):
		"""A switch a lender cannot reverse is worse than no switch."""
		before = published_portal_routes()
		set_portal_switches(0, 0)
		set_portal_switches(1, 1)

		self.assertEqual(published_portal_routes(), before)


class TestPortalBranding(LendingTestSuite):
	"""What a lender sets on one desk form, and where it comes out.

	The goal these serve is in PORTAL_CUSTOMIZATION_PLAN.md part B: a borrower of the
	bank that runs this portal should not be able to tell which app built it. So the
	tests are about two things. That nothing a lender leaves blank changes anything,
	because that is what makes these settings safe to add to a site already running.
	And that everything a lender does fill in reaches the page, the tokens and the
	PDFs, rather than only the one place it was first wired to.
	"""

	def tearDown(self):
		set_branding()
		frappe.local.form_dict = frappe._dict()

	def test_an_unnamed_portal_falls_back_to_ours(self):
		set_branding()

		self.assertEqual(brand_name(), DEFAULT_BRAND_NAME)

	def test_a_named_portal_is_called_what_the_lender_called_it(self):
		set_branding(portal_brand_name="Ganges Finance")

		self.assertEqual(brand_name(), "Ganges Finance")
		self.assertEqual(shell_payload("Loans", "Apply", [])["brand_name"], "Ganges Finance")

	def test_without_a_logo_the_frame_shows_the_name(self):
		set_branding(portal_brand_name="Ganges Finance")
		payload = brand_payload()

		self.assertEqual(payload["brand_logo"], "")
		self.assertEqual(payload["show_wordmark"], 1)

	def test_with_a_logo_the_frame_shows_the_logo_instead_of_the_name(self):
		"""Both are written into the page, so exactly one of them has to be dropped."""
		set_branding(portal_brand_name="Ganges Finance", portal_logo="/files/ganges.png")
		payload = brand_payload()

		self.assertEqual(payload["brand_logo"], "/files/ganges.png")
		self.assertEqual(payload["show_wordmark"], 0)
		# The name still travels, because it is the logo's alt text and the PDFs' fallback.
		self.assertEqual(payload["brand_name"], "Ganges Finance")

	def test_the_public_pages_carry_the_brand_too(self):
		"""/apply and /track wear no borrower shell, so they answer for it themselves."""
		set_branding(portal_brand_name="Ganges Finance", portal_logo="/files/ganges.png")

		for payload in (get_apply_page(), get_track_page()):
			self.assertEqual(payload["brand_name"], "Ganges Finance")
			self.assertEqual(payload["brand_logo"], "/files/ganges.png")

	def test_a_support_address_becomes_something_to_press(self):
		set_branding(portal_support_email="grievance@ganges.example.com")
		payload = brand_payload()

		self.assertEqual(payload["support_email"], "grievance@ganges.example.com")
		self.assertEqual(payload["support_href"], "mailto:grievance@ganges.example.com")

	def test_no_support_address_leaves_the_footer_nothing_to_show(self):
		set_branding()

		self.assertEqual(brand_payload()["support_email"], "")

	def test_no_colours_leave_frappe_ui_to_paint_the_portal(self):
		"""Every block that wears a colour falls back to frappe-ui's own, so none is sent."""
		set_branding()

		self.assertEqual(brand_payload()["brand_style"], "")

	def test_both_colours_reach_the_page_from_the_desk_form(self):
		set_branding(portal_primary_color="#004c8f", portal_secondary_color="#ed232a")
		style = brand_payload()["brand_style"]

		self.assertIn("--portal-primary: #004c8f;", style)
		self.assertIn("--portal-action: #ed232a;", style)

	def test_the_public_pages_carry_the_colours_too(self):
		set_branding(portal_primary_color="#004c8f")

		for payload in (get_apply_page(), get_track_page()):
			self.assertIn("--portal-primary: #004c8f;", payload["brand_style"])

	def test_the_secondary_colour_fills_the_buttons(self):
		"""HDFC: a navy bank with red buttons."""
		tokens = brand_tokens("#004c8f", "#ed232a")

		self.assertEqual(tokens["--portal-primary"], "#004c8f")
		self.assertEqual(tokens["--portal-action"], "#ed232a")
		self.assertEqual(tokens["--portal-action-ink"], "#ffffff")

	def test_without_a_secondary_colour_the_buttons_take_the_primary(self):
		"""Axis: one maroon, and a portal that still has something to press."""
		tokens = brand_tokens("#800000", None)

		self.assertEqual(tokens["--portal-action"], "#800000")

	def test_a_secondary_colour_alone_paints_only_the_buttons(self):
		style = brand_style(None, "#ed232a")

		self.assertIn("--portal-action: #ed232a;", style)
		self.assertNotIn("portal-header", style)
		self.assertNotIn("bg-surface-sidebar", style)

	def test_a_light_colour_carries_dark_ink_and_a_saturated_one_white(self):
		"""Canara: dark on its yellow buttons, white on its blue header."""
		tokens = brand_tokens("#019eec", "#ffb600")

		self.assertEqual(tokens["--portal-action-ink"], "#171717")
		self.assertEqual(tokens["--portal-primary-ink"], "#ffffff")

	def test_a_saturated_orange_carries_white_where_wcag_would_hand_it_black(self):
		"""The WCAG ratio prefers black on #ef6f21, 6.0 to 3.0; the eye, and APCA, prefer white."""
		self.assertEqual(brand_tokens("#ef6f21", None)["--portal-primary-ink"], "#ffffff")
		# A truly light colour still gets the dark ink.
		self.assertEqual(brand_tokens("#ff9f1c", None)["--portal-primary-ink"], "#171717")

	def test_a_header_button_takes_the_secondary_only_where_it_stands_out(self):
		"""SBI's cyan clears 3:1 on its navy; HDFC's red, at 2:1, would be a smudge."""
		self.assertEqual(brand_tokens("#292075", "#00b5ef")["--portal-header-action"], "#00b5ef")
		self.assertEqual(brand_tokens("#004c8f", "#ed232a")["--portal-header-action"], "#ffffff")

	def test_the_primary_colour_tints_the_sidebar_and_nothing_beside_it(self):
		style = brand_style("#004b8e", "#ed232a")

		# A trace of blue in the rail's greys, set on the sidebar alone.
		self.assertIn(".borrower-portal .bg-surface-sidebar { --surface-sidebar: #f5f9fc;", style)
		self.assertNotIn(":root { --surface", style)

	def test_the_header_is_a_band_of_the_primary_colour_in_its_own_ink(self):
		style = brand_style("#004b8e", "#ed232a")

		self.assertIn(".borrower-portal .portal-header { background-color: var(--portal-primary);", style)
		self.assertIn("--ink-gray-9: var(--portal-primary-ink);", style)

	def test_a_done_step_is_a_wash_of_the_primary_with_a_tick_that_can_be_seen(self):
		"""HDFC's navy is dark enough as it is; Canara's blue is darkened to reach 3:1."""
		hdfc = brand_tokens("#004b8e", None)
		self.assertEqual(hdfc["--portal-primary-soft"], "#e0e9f1")
		self.assertEqual(hdfc["--portal-primary-deep"], "#004b8e")

		canara = brand_tokens("#019eec", None)
		tick = contrast(channels(canara["--portal-primary-deep"]), channels(canara["--portal-primary-soft"]))
		self.assertGreaterEqual(tick, 3.0)
		self.assertNotEqual(canara["--portal-primary-deep"], "#019eec")

	def test_the_borrowers_initial_wears_the_same_wash_as_a_done_step(self):
		style = brand_style("#004b8e", None)

		self.assertIn(".borrower-portal .portal-avatar { --surface-gray-2: var(--portal-primary-soft);", style)
		self.assertNotIn("portal-avatar", brand_style(None, "#ed232a"))

	def test_grey_buttons_and_table_bands_wear_a_wash_of_the_secondary(self):
		style = brand_style("#004c8f", "#ed232a")

		# A button marked plain -- the statement's period shortcuts -- stays grey.
		self.assertIn(
			'.borrower-portal button.bg-surface-gray-2:not(.portal-plain):not([role="combobox"]) { background-color: var(--portal-action-soft);',
			style,
		)
		self.assertEqual(brand_tokens("#004c8f", "#ed232a")["--portal-action-soft"], "#fde5e5")

	def test_a_label_on_a_wash_reads_as_body_text_even_while_pressed(self):
		"""4.5:1 on the deepest of the three washes, for a dark red and a light yellow alike."""
		for secondary in ("#ed232a", "#ffb600", "#00b5ef"):
			tokens = brand_tokens("#004c8f", secondary)
			label = channels(tokens["--portal-action-deep"])
			for ground in ("--portal-action-soft", "--portal-action-soft-hover", "--portal-action-soft-active"):
				self.assertGreaterEqual(contrast(label, channels(tokens[ground])), 4.5, (secondary, ground))

	def test_the_footer_wears_the_sidebars_tint(self):
		style = brand_style("#004b8e", None)

		self.assertIn(".borrower-portal .portal-footer { background-color: #f5f9fc;", style)

	def test_a_grey_primary_colour_leaves_the_sidebar_and_footer_grey(self):
		"""A grey has no hue to lend, and the rounding of one is not a hue."""
		style = brand_style("#777777", None)

		self.assertNotIn("bg-surface-sidebar", style)
		self.assertNotIn("portal-footer", style)

	def test_only_a_hex_colour_reaches_the_stylesheet(self):
		"""The value is written into a <style>, so anything else is dropped, not escaped."""
		self.assertEqual(brand_style("red; } body { display: none", "</style><script>"), "")
		self.assertIn("--portal-primary: #aabbcc;", brand_style("ABC", None))


class TestPortalFooter(LendingTestSuite):
	"""The line at the foot of every page, which is the lender's and not ours.

	A borrower reading the bottom of a bank's site expects the copyright notice on one
	side and the policies on the other, and a regulator expects the grievance address
	among them. None of it can be written into the blocks: the notice names a company
	we do not know and the policies are a list whose length we do not know, so both
	are settings read per request. These hold that open -- that the frame repeats one
	link rather than holding a fixed few, because that is what lets a lender add a
	policy without a rebuild of ten pages.
	"""

	def tearDown(self):
		set_footer()
		set_branding()

	def test_an_unwritten_notice_names_the_lender_and_the_year(self):
		set_branding(portal_brand_name="Ganges Finance")
		set_footer()

		self.assertEqual(
			copyright_note(), f"Copyright © {getdate(nowdate()).year} Ganges Finance. All rights reserved."
		)

	def test_an_unnamed_portal_puts_our_name_in_its_own_notice(self):
		set_footer()

		self.assertIn(DEFAULT_BRAND_NAME, copyright_note())

	def test_a_company_that_ends_in_a_stop_does_not_get_two(self):
		"""Most of them do, being an Ltd. The sentence supplies the stop, not the name."""
		set_branding(portal_brand_name="Ganges Finance Ltd.")
		set_footer()

		self.assertIn("Ganges Finance Ltd. All rights reserved.", copyright_note())

	def test_a_lender_writes_its_own_notice(self):
		set_footer(notice="© Ganges Finance. A Ganges Group company.")

		self.assertEqual(copyright_note(), "© Ganges Finance. A Ganges Group company.")

	def test_a_written_notice_still_gets_this_year(self):
		"""A notice with the year typed into it is wrong every January, and nobody edits
		settings to fix that."""
		set_footer(notice="© {year} Ganges Finance.")

		self.assertEqual(copyright_note(), f"© {getdate(nowdate()).year} Ganges Finance.")

	def test_a_notice_carrying_a_stray_brace_is_text_and_not_an_error(self):
		"""The substitution is a replace and not a format, so this renders rather than
		raising on every page of the portal."""
		set_footer(notice="© Ganges Finance {a division of Ganges Group}")

		self.assertEqual(copyright_note(), "© Ganges Finance {a division of Ganges Group}")

	def test_the_links_are_the_lenders_own_in_the_lenders_order(self):
		set_footer(
			links=(
				("User Agreement", "/borrower/user-agreement"),
				("Privacy Policy", "/borrower/privacy-policy"),
				("Disclaimer", "https://ganges.example.com/disclaimer"),
			)
		)

		self.assertEqual(
			footer_links(),
			[
				{"footer_label": "User Agreement", "footer_href": "/borrower/user-agreement"},
				{"footer_label": "Privacy Policy", "footer_href": "/borrower/privacy-policy"},
				{"footer_label": "Disclaimer", "footer_href": "https://ganges.example.com/disclaimer"},
			],
		)

	def test_contact_us_follows_them_without_being_typed(self):
		"""A lender is required to publish a grievance address. Leaving it to a row
		someone remembers to add would mean the sites that need it most are the ones
		without it.

		The link reads Contact us and carries the address underneath, because the
		address is what it does and not what it is for.
		"""
		set_footer(links=(("Privacy Policy", "/borrower/privacy-policy"),), support="care@ganges.example.com")

		self.assertEqual(
			footer_links()[-1],
			{"footer_label": "Contact us", "footer_href": "mailto:care@ganges.example.com"},
		)

	def test_no_address_means_no_contact_us(self):
		"""Rather than a Contact us that opens an empty mail window."""
		set_footer(links=(("Privacy Policy", "/borrower/privacy-policy"),))

		self.assertEqual([link["footer_label"] for link in footer_links()], ["Privacy Policy"])

	def test_no_links_and_no_address_leaves_the_row_empty_rather_than_broken(self):
		"""What a site that upgrades into this and sets nothing gets: a bare notice."""
		set_footer()

		self.assertEqual(footer_links(), [])
		self.assertEqual(shell_payload("Loans", "Apply", [])["footer_links"], [])

	def test_a_row_missing_its_destination_is_not_a_link(self):
		"""Both columns are required on the grid, so this is the row saved before the
		field was, and a link to nowhere is worse than no link."""
		set_footer(links=(("Privacy Policy", "/borrower/privacy-policy"),))
		frappe.db.set_value(
			"Portal Footer Link",
			frappe.get_all("Portal Footer Link", pluck="name")[0],
			"url",
			"",
			update_modified=False,
		)

		self.assertEqual(footer_links(), [])

	def test_the_footer_reaches_the_frame_every_page_wears(self):
		set_branding(portal_brand_name="Ganges Finance")
		set_footer(links=(("Privacy Policy", "/borrower/privacy-policy"),))
		payload = shell_payload("Loans", "Apply", [])

		self.assertIn("Ganges Finance", payload["copyright_note"])
		self.assertEqual(payload["footer_links"][0]["footer_label"], "Privacy Policy")

class TestPortalMenu(LendingTestSuite):
	"""The sidebar, which is a list read per request rather than seven blocks per page.

	The rows live in lending.hooks.portal_menu_items and reach the page through
	Frappe's own portal menu. That is what these hold open: that the frame stays a
	single repeated row, and that the list it repeats is this portal's own.
	"""

	def setUp(self):
		self.request = getattr(frappe.local, "request", None)

	def tearDown(self):
		frappe.local.request = self.request
		super().tearDown()

	def declared(self) -> list[dict]:
		return [
			item
			for item in frappe.get_hooks("portal_menu_items")
			if item["route"].startswith(PORTAL_ROUTE_PREFIX)
		]

	def serving(self, route: str) -> dict[str, str]:
		"""The menu as it comes out while `route` is the page being served."""
		frappe.local.request = frappe._dict(path=route)

		return {row["nav_title"]: row["nav_current"] for row in nav_items()}

	def test_the_menu_is_the_one_declared_in_hooks(self):
		"""In the order declared, with nothing dropped on the way to the page."""
		rows = nav_items()

		self.assertEqual(
			[(row["nav_title"], row["nav_route"]) for row in rows],
			[(item["title"], item["route"]) for item in self.declared()],
		)

	def test_another_portals_rows_are_left_to_it(self):
		"""get_portal_sidebar_items answers for the whole site, ERPNext's portal included."""
		routes = {row["nav_route"] for row in nav_items()}

		self.assertNotIn("/orders", routes)
		self.assertNotIn("/invoices", routes)

	def test_the_page_being_served_is_the_row_that_lights(self):
		marks = self.serving("/borrower-portal/statement")

		self.assertEqual(marks["Statement of account"], "page")
		self.assertEqual(marks["Account overview"], "false")
		self.assertEqual([*marks.values()].count("page"), 1)

	def test_a_detail_page_lights_the_list_it_belongs_to(self):
		"""A loan has no row of its own, and a page with nothing lit reads as lost."""
		self.assertEqual(self.serving("/borrower-portal/loan/LOAN-0001")["Loan accounts"], "page")
		self.assertEqual(
			self.serving("/borrower-portal/application/LN-APP-0001")["Application"], "page"
		)

	def test_a_list_is_not_swallowed_by_the_section_beside_it(self):
		"""/borrower-portal/applications starts with /borrower-portal/application, and is not one."""
		marks = self.serving("/borrower-portal/applications")

		self.assertEqual(marks["Application"], "page")
		self.assertEqual([*marks.values()].count("page"), 1)

	def test_off_a_request_the_menu_still_comes_out(self):
		"""An /api call on one of these endpoints is serving no page at all."""
		frappe.local.request = None
		marks = {row["nav_title"]: row["nav_current"] for row in nav_items()}

		self.assertEqual(len(marks), len(self.declared()))
		self.assertNotIn("page", marks.values())

class TestPortalRail(LendingTestSuite):
	"""The two icons in the rail, and the pages behind them.

	Both were links to "#" until these existed, so the first thing held open here is
	that they go somewhere. The rest is what they answer with: a search that can only
	return what this login already owns, and a notification list that separates what
	the borrower has to do from what has merely happened.
	"""

	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		set_loan_accrual_frequency("Monthly")
		create_loan_product(
			PRODUCT,
			PRODUCT,
			500000,
			8.4,
			repayment_schedule_type="Monthly as per repayment start date",
		)

		make_website_user(ALPHA_USER)
		make_website_user(BETA_USER)
		make_portal_customer(ALPHA_CUSTOMER, ALPHA_USER)
		make_portal_customer(BETA_CUSTOMER, BETA_USER)

		self.alpha_loan = make_submitted_loan(ALPHA_CUSTOMER).name
		self.beta_loan = make_submitted_loan(BETA_CUSTOMER).name
		self.alpha_application = make_application(ALPHA_CUSTOMER)

		frappe.db.commit()  # nosemgrep

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()
		super().tearDown()

	def search(self, query: str) -> dict:
		frappe.set_user(ALPHA_USER)
		frappe.local.form_dict = frappe._dict({"q": query})

		return find()

	# --- the rail -------------------------------------------------------------------

	def test_the_search_page_is_gone(self):
		"""Search is the Ctrl+K palette on every page, so there is no page of it left
		to serve -- nor a sidebar row pointing at one."""
		self.assertNotIn("/search", published_portal_routes())

	def test_the_notifications_page_is_gone(self):
		"""The panel says everything the page said, and a bell with two answers is one
		answer too many. Asserted on the served routes rather than on the source,
		because a page left published outlives whatever built it."""
		self.assertNotIn("/notifications", published_portal_routes())

	# --- search ---------------------------------------------------------------------

	def test_a_product_finds_loans_and_nothing_that_is_not_one(self):
		"""Asserted on the answer rather than on the fixture: this database is not rolled
		back between runs, so the borrower holds hundreds of loans by now and the one
		this test made need not be among the first page of them."""
		results = self.search(PRODUCT)["results"]

		self.assertTrue(results)
		for row in results:
			self.assertIn(PRODUCT.lower(), " ".join(row.values()).lower())

	def test_a_loan_is_found_by_its_number(self):
		results = self.search(self.alpha_loan)["results"]

		self.assertEqual([row["url"] for row in results], [f"/borrower-portal/loan/{self.alpha_loan}"])

	def test_an_application_is_found_and_opens_its_own_page(self):
		results = self.search(self.alpha_application)["results"]

		self.assertEqual(
			[(row["kind"], row["url"]) for row in results],
			[("Application", f"/borrower-portal/application/{self.alpha_application}")],
		)

	def test_a_search_cannot_reach_another_borrowers_loan(self):
		"""The one that matters. Search reads the same scoped lists every page reads."""
		results = self.search(self.beta_loan)["results"]

		self.assertEqual(results, [])

	def test_every_word_has_to_match(self):
		"""Two words narrow the answer; they do not widen it."""
		self.assertTrue(self.search(PRODUCT)["results"])
		self.assertEqual(self.search(f"{PRODUCT} nothing-matches-this")["results"], [])

	def test_an_empty_box_opens_holding_somewhere_to_go(self):
		"""The desk's command bar offers the places you can go before you type, and a
		borrower with no loans yet has nothing else worth offering."""
		payload = self.search("")

		self.assertEqual(
			[row["url"] for row in payload["results"]],
			[item["route"] for item in frappe.get_hooks("portal_menu_items")][:RESULT_LIMIT],
		)
		self.assertEqual({row["kind"] for row in payload["results"]}, {"Page"})
		self.assertEqual(payload["note"], "")

	def test_a_page_is_findable_by_name_like_anything_else(self):
		"""The pages are in the same list the records are, so one query searches both."""
		results = self.search("interest certificate")["results"]

		self.assertEqual(
			[(row["kind"], row["url"]) for row in results], [("Page", "/borrower-portal/certificate")]
		)

	def test_a_search_that_matches_everything_is_cut_down(self):
		"""Held open without the hundreds of records it would take to cause it."""
		self.assertIn(str(RESULT_LIMIT), results_note("loan", RESULT_LIMIT + 10))
		self.assertIn(str(RESULT_LIMIT + 10), results_note("loan", RESULT_LIMIT + 10))

	def test_the_palette_never_answers_past_its_limit(self):
		"""The fixture's product name matches every loan it has made, and this database
		is not rolled back between runs, so there are more of them than fit."""
		self.assertLessEqual(len(self.search(PRODUCT)["results"]), RESULT_LIMIT)

	# --- notifications --------------------------------------------------------------

	def test_a_draft_application_is_work_waiting_on_the_borrower(self):
		"""A draft is the borrower's to submit, so it belongs on the list that asks."""
		rows = attention_rows(
			[
				{"name": "APP-1", "url": "/borrower/application/APP-1", "product": PRODUCT,
					"note": "Submit to start the review", "stage": "Action required",
					"needs_borrower": True},
				{"name": "APP-2", "url": "/borrower/application/APP-2", "product": PRODUCT,
					"note": "", "stage": "Under review", "needs_borrower": False},
			],
			[],
		)

		self.assertEqual([row["url"] for row in rows], ["/borrower/application/APP-1"])

	def test_an_instalment_coming_due_is_on_the_list_too(self):
		instalment = {
			"product": PRODUCT,
			"detail": "Principal 900 · interest 100",
			"date": "12 Oct 2026",
			"amount": "1,000",
		}
		rows = attention_rows([], [dict(instalment, url="/borrower/loan/LOAN-0001")])

		self.assertEqual(rows[0]["when"], "Due 12 Oct 2026 · 1,000")
		self.assertEqual(rows[0]["url"], "/borrower/loan/LOAN-0001")

	def test_an_instalment_whose_loan_is_unknown_still_leads_somewhere(self):
		"""A row that looks like a link has to act like one, even with no loan to name."""
		rows = attention_rows([], [{"product": PRODUCT, "detail": "", "date": "z", "amount": "1"}])

		self.assertEqual(rows[0]["url"], "/borrower/loans")

	def test_the_borrowers_own_list_is_capped_and_says_how_long_it_really_is(self):
		frappe.set_user(ALPHA_USER)
		payload = get_notifications()

		self.assertLessEqual(len(payload["attention"]), ATTENTION_LIMIT)
		for row in payload["attention"]:
			self.assertTrue(row["url"].startswith("/borrower/"))
		self.assertTrue(
			payload["attention_note"] == "Nothing to do" or "waiting on you" in payload["attention_note"]
		)

	def test_another_borrowers_work_is_not_on_this_ones_list(self):
		frappe.set_user(BETA_USER)
		urls = [row["url"] for row in get_notifications()["attention"]]

		self.assertNotIn(f"/borrower/application/{self.alpha_application}", urls)

	def test_what_has_happened_comes_out_in_the_same_shape_as_what_is_waiting(self):
		"""One shape is what lets the two tabs share a single row block."""
		rows = activity_rows(
			[{"title": "Repayment received", "sub": PRODUCT, "date": "12 Sep 2026", "amount": "1,000"}]
		)

		self.assertEqual(
			rows,
			[
				{
					"title": "Repayment received",
					"note": PRODUCT,
					"when": "1,000 · 12 Sep 2026",
					# A record of a repayment is still worth opening: it is a line of
					# the statement. No row in either list is a dead end.
					"url": "/borrower/statement",
				}
			],
		)
		self.assertEqual(
			set(rows[0]),
			set(attention_rows([], [{"product": "x", "detail": "y", "date": "z", "amount": "1"}])[0]),
		)

	# --- the double tick -------------------------------------------------------------

	def test_every_row_says_whether_it_has_been_read(self):
		"""The dot on the row is drawn from this and nothing else."""
		frappe.set_user(ALPHA_USER)
		payload = get_notifications()

		for row in payload["attention"] + payload["activity"]:
			self.assertIn("read", row)
			self.assertIsInstance(row["read"], bool)

	def test_the_double_tick_marks_everything_on_the_panel(self):
		frappe.set_user(ALPHA_USER)
		frappe.defaults.clear_user_default(READ_KEY)

		before = get_notifications()
		self.assertTrue(any(not row["read"] for row in before["attention"] + before["activity"]))

		mark_all_as_read()
		after = get_notifications()

		self.assertTrue(all(row["read"] for row in after["attention"] + after["activity"]))

	def test_a_row_that_changes_what_it_says_comes_back_unread(self):
		"""A notification is only the same notification while it says the same thing:
		an instalment whose amount moves is news again, and has to look like it."""
		frappe.set_user(ALPHA_USER)
		mark_all_as_read()
		seen = read_keys()

		row = {"title": PRODUCT, "note": "Principal 900", "when": "Due 12 Oct 2026 · 1,000", "url": "/borrower/loans"}
		moved = dict(row, when="Due 12 Oct 2026 · 1,200")

		self.assertNotEqual(row_key(row), row_key(moved))
		self.assertNotIn(row_key(moved), seen)

	def test_one_borrowers_double_tick_does_not_clear_anothers(self):
		frappe.set_user(BETA_USER)
		frappe.defaults.clear_user_default(READ_KEY)

		frappe.set_user(ALPHA_USER)
		mark_all_as_read()
		self.assertTrue(read_keys())

		frappe.set_user(BETA_USER)
		self.assertEqual(read_keys(), set())

	def test_the_double_tick_writes_only_what_the_server_can_see(self):
		"""Nothing arrives from the browser, so there is nothing to forge: the keys are
		recomputed from this borrower's own rows. It is also what prunes the list --
		a key for a row that has dropped off the panel is simply not rewritten."""
		frappe.set_user(ALPHA_USER)
		frappe.defaults.set_user_default(READ_KEY, json.dumps(["stale-key-from-before"]))
		mark_all_as_read()

		self.assertNotIn("stale-key-from-before", read_keys())

	def test_a_borrower_whose_marks_are_unreadable_is_not_an_error(self):
		"""A hand-edited DefaultValue should cost a borrower their dots, not their page."""
		frappe.set_user(ALPHA_USER)
		frappe.defaults.set_user_default(READ_KEY, "not json")

		self.assertEqual(read_keys(), set())
		self.assertTrue(get_notifications()["activity_note"])


class TestPortalSummaryStrip(LendingTestSuite):
	"""The three cards the overview opens with, and which of them leads.

	A borrower opens the portal to learn three things: where their application has got
	to, what they pay next, and what they still owe. The application leads because it
	is the only one of the three with an answer on the first day -- the two figures
	read "Nothing due" and "No live accounts" until a loan is booked, and a borrower
	who is still applying was meeting a page of blanks.
	"""

	def blocks(self, node) -> list[dict]:
		"""Every block of a page's tree, the node itself included."""
		found = [node]
		for child in node.get("children") or []:
			found.extend(self.blocks(child))

		return found

	def test_a_borrower_with_nothing_in_progress_is_not_shown_an_empty_card(self):
		"""The card stands either way, so the empty payload has to fill it.

		A blank headline would read as a page that failed to load. The em dash and the
		line under it say there is nothing, which is a different thing from saying
		nothing.
		"""
		empty = application_lead([])

		self.assertEqual(empty["application_stage"], "")
		self.assertNotEqual(empty["application_headline"], "")
		self.assertNotEqual(empty["application_note"], "")

	def test_the_card_names_the_newest_application_and_says_how_many_more(self):
		"""One card, several applications: it must not look like the whole story.

		get_applications orders newest first, so the card takes the first row. The
		count under it is what sends a borrower to the table below, and it stays away
		when there is only the one they are already reading.
		"""
		newest = dict(self.application("Home Loan"), note="")
		older = self.application("Personal Loan")

		self.assertEqual(application_lead([newest, older])["application_headline"], "Home Loan")
		self.assertIn("2", application_lead([newest, older])["application_more"])
		self.assertEqual(application_lead([newest])["application_more"], "")

	def application(self, product: str, loan: str = "") -> dict:
		return {
			"name": "APP-1",
			"url": "/borrower-portal/application/APP-1",
			"loan_url": f"/borrower-portal/loan/{loan}" if loan else "",
			"product": product,
			"stage": "Loan sanctioned" if loan else "Under review",
			"stage_tone": "ok" if loan else "info",
			"reference": "APP-1 · initiated 1 January 2026",
			"initiated": "Initiated on 1 January 2026",
			"note": "",
		}

	def test_the_card_opens_the_loan_once_the_application_has_become_one(self):
		"""The card is pressable, and where it goes moves with the application.

		An application under review is a record of the asking, and its own page is the
		only place that shows where it has got to. Once the loan is booked that page is
		history: the borrower pressing a card headed "Loan sanctioned" wants the account,
		not the form they filled in weeks ago.
		"""
		under_review = application_lead([self.application("Home Loan")])
		sanctioned = application_lead([self.application("Home Loan", loan="LOAN-1")])

		self.assertEqual(under_review["application_url"], "/borrower-portal/application/APP-1")
		self.assertEqual(sanctioned["application_url"], "/borrower-portal/loan/LOAN-1")

	def test_a_card_with_nothing_in_progress_offers_nowhere_to_go(self):
		"""The chevron is bound to this key, so an empty one is what hides it."""
		self.assertEqual(application_lead([])["application_url"], "")

	def test_the_card_names_the_application_and_the_day_it_was_raised(self):
		"""Two lines, not the one the table reads.

		The card sets the name above the date, so it needs them apart. A card handed
		the table's joined reference could only print it whole.
		"""
		lead = application_lead([self.application("Home Loan")])

		self.assertEqual(lead["application_name"], "APP-1")
		self.assertEqual(lead["application_initiated"], "Initiated on 1 January 2026")

	def test_the_sanctioned_amount_is_one_line_under_the_outstanding_figure(self):
		"""It was a card of its own, at the weight of the two figures beside it.

		A borrower checks what was sanctioned once, so it reads as a sentence now. The
		sentence is joined in the data layer, because which of the four facts is worth
		saying depends on the account and that is a judgement rather than a layout.
		"""
		loans = [frappe._dict(status="Active", loan_amount=500000, disbursed_amount=300000)]
		line = build_summary(loans, [])["sanctioned_line"]

		self.assertIn(money(500000), line)
		self.assertIn(money(200000), line)

class TestPortalRanking(LendingTestSuite):
	"""What the overview puts first, and what it stops saying twice.

	The page used to lead with a filled black button offering a payment eighteen days
	away, while the two applications actually waiting on the borrower were grey text
	in the middle of a table. What is held open here is the order it reads in now:
	the work first, the button following the work, and every fact said once.
	"""

	def draft(self, name="APP-1", product="Personal Loan"):
		return {
			"name": name,
			"url": f"/borrower/application/{name}",
			"product": product,
			"reference": f"{name} · initiated 24 August 2026",
			"note": "Submit to start the review",
			"stage": "Action required",
			"stage_tone": "warn",
			"needs_borrower": True,
			"amount": money(100000),
		}

	def instalment(self, product="Personal Loan"):
		return {
			"date": "09 Oct 2026",
			"product": product,
			"detail": "Principal 900 · interest 100",
			"amount": money(1000),
			"url": "/borrower/loan/LOAN-0001",
		}

	# --- what counts as waiting ------------------------------------------------------

	def test_an_application_under_review_is_not_waiting_on_the_borrower(self):
		"""The strip is work they can do. An application with the lender is not that."""
		reviewing = dict(self.draft(), needs_borrower=False, stage="Under review")

		self.assertEqual(waiting_on_borrower([reviewing]), [])

	def test_a_draft_opens_where_it_is_cleared(self):
		rows = waiting_on_borrower([self.draft(), dict(self.draft(), needs_borrower=False)])

		self.assertEqual([row["url"] for row in rows], ["/borrower/application/APP-1"])
		self.assertEqual(rows[0]["note"], "Submit to start the review")

	def test_the_strip_leaves_the_payment_to_the_button(self):
		"""The two halves of the page's one request must not both make it.

		A strip that also carried the instalment would put the payment on the page
		twice -- once as a row and once as the button right above it -- which is the
		habit the strip was added to break, reintroduced by the fix for it.
		"""
		source = inspect.getsource(waiting_on_borrower)

		self.assertNotIn("schedule", source)
		self.assertNotIn(REPAYMENTS_ROUTE, source)

	# --- the button ------------------------------------------------------------------

	def test_the_button_is_the_payment_page_either_way(self):
		"""The destination was never wrong. Only the insistence was."""
		quiet = next_action(due_soon=False)
		loud = next_action(due_soon=True)

		self.assertEqual(quiet["action_href"], REPAYMENTS_ROUTE)
		self.assertEqual(loud["action_href"], REPAYMENTS_ROUTE)
		self.assertEqual(quiet["action_label"], loud["action_label"])

	def test_the_button_only_insists_when_a_payment_is_near(self):
		"""The whole complaint in one assertion: eighteen days out, this was "1"."""
		self.assertEqual(next_action(due_soon=False)["action_urgent"], "0")
		self.assertEqual(next_action(due_soon=True)["action_urgent"], "1")

	# --- what is no longer said twice -------------------------------------------------

	def test_one_live_account_reads_its_standing_in_its_own_row(self):
		"""The head said "All accounts regular" over a single row saying "Regular"."""
		one = [frappe._dict(name="L-1", status="Disbursed")]
		two = [frappe._dict(name="L-1", status="Disbursed"), frappe._dict(name="L-2", status="Active")]

		self.assertEqual(account_status(one)["account_status"], "")
		self.assertEqual(account_status(two)["account_status"], "All accounts regular")

	def test_a_fully_drawn_loan_gets_progress_where_it_got_its_own_figure_back(self):
		"""Sanctioned equals disbursed once a loan is fully drawn, so the line was
		repeating the figure above it. How far through they are is the fact that is
		nowhere else on the page."""
		drawn = standing_line(sanctioned=300000, undrawn=0, drawn=300000, repaid=50000)
		partly = standing_line(sanctioned=300000, undrawn=100000, drawn=200000, repaid=0)

		self.assertIn(money(50000), drawn)
		self.assertNotIn("sanctioned", drawn.lower())
		self.assertIn("undrawn", partly.lower())

	def test_nothing_sanctioned_still_says_nothing(self):
		self.assertEqual(standing_line(sanctioned=0, undrawn=0, drawn=0, repaid=0), "")

	def test_one_loans_instalments_stop_repeating_its_name(self):
		"""Four rows of one fixed instalment differ only in date. The name goes up to
		the card's subtitle and the row leads with what actually moves."""
		rows = name_once([self.instalment(), self.instalment()])

		self.assertEqual([row["sub"] for row in rows], ["", ""])
		self.assertEqual([row["title"] for row in rows], [row["detail"] for row in rows])

	def test_two_loans_keep_their_names_on_every_row(self):
		"""With more than one loan the name is what tells the rows apart."""
		rows = name_once([self.instalment("Personal Loan"), self.instalment("Demand Loan")])

		self.assertEqual([row["title"] for row in rows], ["Personal Loan", "Demand Loan"])
		self.assertEqual([row["sub"] for row in rows], [row["detail"] for row in rows])

class TestPortalActivityList(LendingTestSuite):
	"""The overview's activity list: a line of dots, and one sentence per event.

	It reads the way the desk's own timeline reads, because it answers the same
	question -- has the thing I did landed yet -- and a borrower checking whether their
	payment went through should not have to subtract a date from today to find out.
	"""

	def test_an_event_from_today_is_not_told_in_hours(self):
		"""The reason days_ago exists rather than frappe.utils.pretty_date.

		These events carry a posting date, which pretty_date reads as midnight: a
		repayment entered this morning came back as "14 hours ago", and one entered
		late last night as "yesterday", though both happened on the same day.
		"""
		self.assertEqual(days_ago(nowdate()), "Today")
		self.assertEqual(days_ago(add_days(nowdate(), -1)), "Yesterday")

	def test_how_long_ago_is_told_in_the_unit_that_fits(self):
		"""Days for a week, then weeks, then months. "56 days ago" is arithmetic."""
		said = [days_ago(add_days(nowdate(), -days)) for days in (3, 8, 40, 400)]

		self.assertEqual(said, ["3 days ago", "1 week ago", "1 month ago", "1 year ago"])


class TestPortalDisbursementRequest(LendingTestSuite):
	"""A borrower asks for money on a sanctioned loan; staff pay it out.

	The request is a draft Loan Disbursement. What matters is that it is only ever a
	draft, only on the borrower's own loan, and never for more than the loan has left.
	"""

	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		set_loan_accrual_frequency("Monthly")
		create_loan_product(
			PRODUCT,
			PRODUCT,
			500000,
			8.4,
			repayment_schedule_type="Monthly as per repayment start date",
		)

		make_website_user(ALPHA_USER)
		make_website_user(BETA_USER)
		make_portal_customer(ALPHA_CUSTOMER, ALPHA_USER)
		make_portal_customer(BETA_CUSTOMER, BETA_USER)

		self.alpha_loan = make_submitted_loan(ALPHA_CUSTOMER).name
		self.beta_loan = make_submitted_loan(BETA_CUSTOMER).name
		frappe.db.commit()  # nosemgrep

		frappe.set_user(ALPHA_USER)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()

	def ask(self, loan, amount):
		frappe.local.form_dict = frappe._dict({"name": loan, "amount": amount})
		return request_disbursement()

	def drafts(self, loan):
		return frappe.get_all(
			"Loan Disbursement",
			filters={"against_loan": loan},
			fields=["name", "docstatus", "disbursed_amount"],
			ignore_permissions=True,
		)

	def test_a_sanctioned_loan_offers_its_whole_amount(self):
		frappe.local.form_dict = frappe._dict({"name": self.alpha_loan})
		drawdown = get_loan_detail()["drawdown"]

		self.assertTrue(drawdown["open"])
		self.assertEqual(drawdown["available"], 100000)

	def test_a_request_raises_a_draft_and_nothing_more(self):
		self.ask(self.alpha_loan, 40000)

		(draft,) = self.drafts(self.alpha_loan)
		self.assertEqual(draft.docstatus, 0)
		self.assertEqual(draft.disbursed_amount, 40000)
		# The loan itself is untouched until staff submit the draft.
		self.assertEqual(frappe.db.get_value("Loan", self.alpha_loan, "status"), "Sanctioned")
		self.assertTrue(
			frappe.db.exists(
				"Comment", {"reference_doctype": "Loan Disbursement", "reference_name": draft.name}
			)
		)

	def test_another_borrowers_loan_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.ask(self.beta_loan, 40000)

		self.assertEqual(self.drafts(self.beta_loan), [])

	def test_more_than_the_loan_has_left_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.ask(self.alpha_loan, 100001)

		self.assertEqual(self.drafts(self.alpha_loan), [])

	def test_nothing_is_not_an_amount(self):
		with self.assertRaises(frappe.ValidationError):
			self.ask(self.alpha_loan, 0)

	def test_a_waiting_draft_stands_in_for_the_button(self):
		self.ask(self.alpha_loan, 40000)

		with self.assertRaises(frappe.ValidationError):
			self.ask(self.alpha_loan, 10000)

		frappe.local.form_dict = frappe._dict({"name": self.alpha_loan})
		drawdown = get_loan_detail()["drawdown"]

		self.assertFalse(drawdown["open"])
		self.assertIn(money(40000), drawdown["note"])
		self.assertEqual(len(self.drafts(self.alpha_loan)), 1)



class TestPortalAccountSwitch(LendingTestSuite):
	"""A borrower with several loans picks one, and the portal then reads that one alone.

	The choice is the borrower's own record of which loan to show, so it must only ever
	name one of their loans: a choice that names somebody else's is refused, and one
	that stops being theirs is ignored.
	"""

	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		set_loan_accrual_frequency("Monthly")
		create_loan_product(
			PRODUCT,
			PRODUCT,
			500000,
			8.4,
			repayment_schedule_type="Monthly as per repayment start date",
		)

		make_website_user(ALPHA_USER)
		make_website_user(BETA_USER)
		make_portal_customer(ALPHA_CUSTOMER, ALPHA_USER)
		make_portal_customer(ALPHA_OTHER_CUSTOMER, ALPHA_USER)
		make_portal_customer(BETA_CUSTOMER, BETA_USER)

		self.alpha_loan = make_submitted_loan(ALPHA_CUSTOMER).name
		self.alpha_other_loan = make_submitted_loan(ALPHA_OTHER_CUSTOMER).name
		self.beta_loan = make_submitted_loan(BETA_CUSTOMER).name
		frappe.db.commit()  # nosemgrep

		frappe.set_user(ALPHA_USER)

	def tearDown(self):
		frappe.defaults.clear_user_default(CHOSEN_LOAN_KEY, ALPHA_USER)
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()

	def test_a_borrower_with_several_loans_is_asked_to_choose(self):
		self.assertIs(get_dashboard()["choose_account"], True)

		page = get_accounts_page()
		names = [row["name"] for row in page["accounts"]]

		self.assertIn(self.alpha_loan, names)
		self.assertIn(self.alpha_other_loan, names)
		self.assertNotIn(self.beta_loan, names)
		self.assertFalse(any(row["chosen"] for row in page["accounts"]))
		self.assertIs(page["can_switch"], True)

	def test_the_chosen_loan_is_the_one_every_page_reads(self):
		choose_account(self.alpha_other_loan)

		dashboard = get_dashboard()
		self.assertIs(dashboard["choose_account"], False)
		self.assertEqual([row["name"] for row in dashboard["accounts"]], [self.alpha_other_loan])
		self.assertIs(dashboard["can_switch"], True)

		self.assertEqual(default_loan(), self.alpha_other_loan)
		self.assertEqual([row.name for row in owned_loans()[1]], [self.alpha_other_loan])

		chosen = [row["name"] for row in get_accounts_page()["accounts"] if row["chosen"]]
		self.assertEqual(chosen, [self.alpha_other_loan])

	def test_a_loan_named_in_the_request_still_wins_over_the_choice(self):
		choose_account(self.alpha_other_loan)

		self.assertEqual([row.name for row in owned_loans(self.alpha_loan)[1]], [self.alpha_loan])

	def test_choosing_another_borrowers_loan_is_refused(self):
		choose_account(self.alpha_loan)

		with self.assertRaises(frappe.PermissionError):
			choose_account(self.beta_loan)

		self.assertEqual(default_loan(), self.alpha_loan)

	def test_a_choice_that_is_no_longer_yours_is_ignored(self):
		frappe.defaults.set_user_default(CHOSEN_LOAN_KEY, self.beta_loan)

		self.assertIs(get_dashboard()["choose_account"], True)
		self.assertNotEqual(default_loan(), self.beta_loan)

	def test_a_borrower_with_one_loan_is_never_asked(self):
		# A borrower of its own: every setUp in this file gives Beta another loan, and
		# nothing rolls them back.
		frappe.set_user("Administrator")
		make_website_user(SINGLE_USER)
		make_portal_customer(SINGLE_CUSTOMER, SINGLE_USER)
		loan = frappe.db.get_value("Loan", {"applicant": SINGLE_CUSTOMER, "docstatus": 1}, "name")
		loan = loan or make_submitted_loan(SINGLE_CUSTOMER).name

		frappe.set_user(SINGLE_USER)
		dashboard = get_dashboard()

		self.assertIs(dashboard["choose_account"], False)
		self.assertIs(dashboard["can_switch"], False)
		self.assertEqual([row["name"] for row in dashboard["accounts"]], [loan])
