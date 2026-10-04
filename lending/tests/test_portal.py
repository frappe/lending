# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import glob
import inspect
import json
import math
import re
from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_years, getdate, nowdate
from frappe.utils.safe_exec import is_safe_exec_enabled

from lending.loan_management.doctype.lending_settings.lending_settings import (
	APPLY_ROUTE,
	portal_app,
	sync_portal_pages,
)
from lending.loan_origination.doctype.loan_lead.loan_lead import convert_to_loan_application
from lending.loan_origination.doctype.loan_lead.test_loan_lead import activate_loan_lead_workflow
from lending.portal.accounts import create_customer, customer_for_email, link_portal_user
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
	create_customer_lead,
	get_apply_page,
	get_new_application_page,
	get_track_page,
	read_product,
	send_account_code,
	send_mobile_code,
	submit_lead,
	track_application,
)
from lending.portal.brand import (
	DARK_GROUND,
	brand_style,
	brand_tokens,
	channels,
	contrast,
	dark_tokens,
	ink_for,
)
from lending.portal.colour import lift
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
	enquiry_lead,
	footer_links,
	get_applications,
	get_dashboard,
	get_loans,
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
from lending.portal.presets import PRESETS, resolve
from lending.portal.print_formats import FORMATS, STATEMENT_FORMAT
from lending.portal.print_formats import ensure as ensure_print_formats
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

# One login holding several customers is the real shape of the data.
ALPHA_CUSTOMER = "_Test Portal Alpha"
ALPHA_OTHER_CUSTOMER = "_Test Portal Alpha Second"
BETA_CUSTOMER = "_Test Portal Beta"

SINGLE_USER = "portal-single@example.com"
SINGLE_CUSTOMER = "_Test Portal Single"

# Its own customer: the shared-record test pins a Contact to it and the DB is not rolled back.
SHARED_CUSTOMER = "_Test Portal Alpha Shared"

PRODUCT = "Personal Loan"

# National number only; the portal must add the country code itself.
MOBILE = "9812345678"

PERSON_EMAIL = "_test-portal-person@example.com"
COMPANY_EMAIL = "_test-portal-company@example.com"
DESK_EMAIL = "_test-portal-desk@example.com"


def set_portal_switches(portal: int, public_apply: int):
	frappe.db.set_single_value(
		"Lending Settings",
		{"enable_borrower_portal": portal, "enable_public_apply": public_apply},
	)
	sync_portal_pages()


def published_portal_routes() -> set[str]:
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


BRAND_FIELDS = (
	"portal_brand_name",
	"portal_logo",
	"portal_support_email",
	"portal_primary_color",
	"portal_secondary_color",
)


def set_branding(**values):
	# Saved, not set_single_value, so Lending Settings.on_update republishes the pages.
	settings = frappe.get_doc("Lending Settings")
	settings.update({field: values.get(field) for field in BRAND_FIELDS})
	settings.save()


def oklch_hue(colour):
	"""Hue in degrees, or None for a grey, which has none."""

	def linear(part):
		part /= 255
		return part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4

	red, green, blue = (linear(part) for part in channels(colour))
	long = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
	medium = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3)
	short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)
	a = 1.9779984951 * long - 2.4285922050 * medium + 0.4505937099 * short
	b = 0.0259040371 * long + 0.7827717662 * medium - 0.8086757660 * short

	if math.hypot(a, b) < 0.02:
		return None

	return math.degrees(math.atan2(b, a)) % 360


def set_footer(notice=None, links=(), support=None):
	settings = frappe.get_doc("Lending Settings")
	settings.portal_copyright = notice
	settings.portal_support_email = support
	settings.portal_footer_links = []
	for label, url in links:
		settings.append("portal_footer_links", {"label": label, "url": url})
	settings.save()


def setUpModule():
	set_portal_switches(1, 1)
	# ERPNextTestSuite rolls back after every test and never commits, so a fresh site would lose the switches.
	frappe.db.commit()  # nosemgrep


def make_website_user(email: str) -> str:
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

	frappe.get_doc("User", email).add_roles("Customer")

	return email


def make_portal_customer(name: str, user: str) -> str:
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
		self.alpha_application = make_application(ALPHA_CUSTOMER)
		self.beta_application = make_application(BETA_CUSTOMER)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.form_dict.pop("name", None)
		super().tearDown()

	def as_alpha(self):
		frappe.set_user(ALPHA_USER)

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

	def test_the_default_loan_is_the_borrowers_own(self):
		self.as_alpha()

		applicant = frappe.db.get_value("Loan", default_loan(), "applicant")

		self.assertIn(applicant, get_portal_customers())

	def test_the_default_application_is_the_borrowers_own(self):
		self.as_alpha()

		self.assertNotEqual(default_application(), self.beta_application)
		self.assertTrue(default_application())

	def test_assert_owns_returns_the_applicant_for_your_own_record(self):
		self.as_alpha()

		self.assertEqual(assert_owns("Loan", self.alpha_loan), ALPHA_CUSTOMER)

	def test_assert_owns_refuses_another_borrowers_record(self):
		self.as_alpha()

		with self.assertRaises(frappe.PermissionError):
			assert_owns("Loan", self.beta_loan)

	def test_an_employees_loan_under_a_customers_name_is_not_theirs(self):
		# A borrower who signs up as "HR-EMP-00001" must not inherit that employee's records.
		frappe.db.set_value("Loan", self.alpha_loan, "applicant_type", "Employee")
		frappe.db.set_value("Loan Application", self.alpha_application, "applicant_type", "Employee")
		self.as_alpha()
		customers = get_portal_customers()

		with self.assertRaises(frappe.PermissionError):
			assert_owns("Loan", self.alpha_loan)
		with self.assertRaises(frappe.PermissionError):
			assert_owns("Loan Application", self.alpha_application)

		self.assertNotIn(self.alpha_loan, [row.name for row in get_loans(customers)])
		self.assertNotIn(
			self.alpha_application, [row["name"] for row in get_applications(customers)]
		)

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

		with (
			patch("lending.portal.applications.default_application", return_value=None),
			patch("lending.portal.applications.open_lead", return_value=None),
		):
			self.assertIs(get_application_detail()["has_application"], False)

	def test_a_loan_detail_with_no_name_opens_the_default_loan(self):
		self.as_alpha()
		frappe.form_dict.pop("name", None)

		self.assertEqual(get_loan_detail()["crumb"], PRODUCT)

	def test_a_missing_loan_and_another_borrowers_loan_are_indistinguishable(self):
		self.as_alpha()

		frappe.form_dict["name"] = self.beta_loan
		with self.assertRaises(frappe.PermissionError) as theirs:
			get_loan_detail()

		frappe.form_dict["name"] = "LOAN-DOES-NOT-EXIST"
		with self.assertRaises(frappe.PermissionError) as missing:
			get_loan_detail()

		self.assertEqual(str(theirs.exception), str(missing.exception))


class TestPortalGuestEndpoints(LendingTestSuite):
	# Rate limits are inert here: frappe's decorator returns early without an HTTP request.

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
		super().tearDown()

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
		frappe.local.form_dict = frappe._dict({"mobile_number": mobile, "otp": "123456"})
		with patch("lending.portal.apply.telephony_otp") as telephony:
			telephony.return_value.verify_otp.return_value = {"verified": True}
			result = confirm_mobile_code()

		return result["token"]

	def test_a_guest_can_read_the_apply_page(self):
		payload = get_apply_page()

		self.assertIn(PRODUCT, [row["value"] for row in payload["products"]["Individual"]])

	def test_a_code_is_sent_to_the_number_given(self):
		frappe.local.form_dict = frappe._dict({"mobile_number": MOBILE})
		with patch("lending.portal.apply.telephony_otp") as telephony:
			result = send_mobile_code()
			telephony.return_value.send_otp.assert_called_once()

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
		# validate resets this on every save, so mark_mobile_verified must write after it.
		self.assertEqual(lead.mobile_verification_status, "Verified")
		self.assertEqual(lead.lead_source, "Portal")
		self.assertEqual(lead.pan, "ABCDE1234F")
		# A submitted lead would skip every rule step in the Loan Lead Workflow.
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

	def use_lead_workflow(self):
		if not frappe.db.exists("Workflow", "Loan Lead Workflow"):
			self.skipTest("requires the Loan Lead Workflow fixture")

		if not is_safe_exec_enabled():
			self.skipTest("Run Basic Rules runs Server Scripts, which need server_script_enabled")

		frappe.set_user("Administrator")
		activate_loan_lead_workflow(self)
		frappe.set_user("Guest")

	def test_a_portal_lead_runs_only_the_free_basic_rules_as_a_draft(self):
		self.use_lead_workflow()
		self.submission(token=self.mint_token(), date_of_birth=add_years(nowdate(), -30))

		with (
			patch("lending.loan_origination.decisioning.run_pre_qualification_rules") as pre_qualify,
			patch("lending.loan_integrations.bureau.run_bureau_pull_task") as bureau_pull,
		):
			reference = submit_lead()["reference"]

		lead = frappe.db.get_value("Loan Lead", reference, ["docstatus", "workflow_state"], as_dict=True)

		self.assertEqual(lead.docstatus, 0)
		self.assertEqual(lead.workflow_state, "Scrubbing")
		self.assertEqual(frappe.session.user, "Guest")
		# Pre-Qualification pulls a paid bureau report; staff decide that from Desk.
		pre_qualify.assert_not_called()
		bureau_pull.assert_not_called()

	def test_a_rule_that_says_no_leaves_the_lead_at_incoming_with_a_note(self):
		self.use_lead_workflow()
		self.submission(token=self.mint_token(), date_of_birth=add_years(nowdate(), -30))

		with patch(
			"lending.portal.apply.apply_workflow",
			side_effect=frappe.ValidationError("Basic rules declined this applicant."),
		):
			result = submit_lead()

		lead = frappe.db.get_value(
			"Loan Lead",
			result["reference"],
			["workflow_state", "prequalification_status", "mobile_verification_status"],
			as_dict=True,
		)

		self.assertEqual(lead.workflow_state, "Incoming")
		self.assertFalse(lead.prequalification_status)
		self.assertEqual(result["headline"], "Thank you, we have your enquiry")
		self.assertEqual(lead.mobile_verification_status, "Verified")

		note = frappe.db.get_value(
			"Comment",
			{"reference_doctype": "Loan Lead", "reference_name": result["reference"]},
			"content",
		)
		self.assertIn("Run Basic Rules", note)
		self.assertIn("Basic rules declined", note)

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
		# The setup wizard sets this on a real site; CI's site skips the wizard.
		frappe.db.set_single_value("System Settings", "country", "India")

		make_website_user(ALPHA_USER)
		make_website_user(BETA_USER)
		make_portal_customer(ALPHA_CUSTOMER, ALPHA_USER)
		make_portal_customer(ALPHA_OTHER_CUSTOMER, ALPHA_USER)
		make_portal_customer(SHARED_CUSTOMER, ALPHA_USER)
		make_portal_customer(BETA_CUSTOMER, BETA_USER)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()
		super().tearDown()

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
		self.assertEqual(form["forms"][ALPHA_CUSTOMER]["city"], "Mumbai")

	def test_a_landline_does_not_overwrite_the_mobile(self):
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

		self.as_alpha()
		self.post(customer=SHARED_CUSTOMER, email="alpha.private@example.com", mobile="9812340003")
		save_profile()

		self.assertEqual(
			frappe.db.get_value("Contact", shared.name, "email_id"), "shared@example.com"
		)

	def test_an_address_with_no_country_still_saves(self):
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
		application = frappe.get_doc("Loan Application", self.alpha_draft)
		application.status = "Approved"
		application.submit()

		self.as_alpha()
		self.post()

		with self.assertRaises(frappe.ValidationError):
			upload_document()

	def test_a_draft_of_your_own_gets_as_far_as_the_file(self):
		# No multipart request in a test, so only the guards ahead of the file are proven.
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


class TestPortalCustomerLead(PortalPeople):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("User", BETA_USER, "mobile_no", MOBILE)

	def ask(self, user, **overrides):
		frappe.set_user(user)
		frappe.local.form_dict = frappe._dict(
			{"loan_product": PRODUCT, "loan_amount": 100000, **overrides}
		)

		return create_customer_lead()

	def test_a_guest_cannot_raise_one(self):
		with self.assertRaises(frappe.PermissionError):
			self.ask("Guest")

	def test_the_lead_is_a_draft_joined_to_the_borrowers_customer(self):
		result = self.ask(BETA_USER)

		lead = frappe.db.get_value(
			"Loan Lead",
			result["reference"],
			["docstatus", "customer", "email", "mobile_number", "mobile_verification_status"],
			as_dict=True,
		)

		self.assertEqual(lead.docstatus, 0)
		self.assertEqual(lead.customer, BETA_CUSTOMER)
		self.assertEqual(lead.email, BETA_USER)
		self.assertEqual(lead.mobile_number, f"+91{MOBILE}")
		self.assertEqual(lead.mobile_verification_status, "Verified")
		self.assertNotIn("account_token", result)

	def test_who_is_asking_comes_off_the_record_not_the_request(self):
		result = self.ask(
			BETA_USER, applicant_name="Somebody Else", email="else@example.com", mobile_number="9000000009"
		)

		lead = frappe.db.get_value(
			"Loan Lead", result["reference"], ["applicant_name", "email", "mobile_number"], as_dict=True
		)

		self.assertEqual(lead.applicant_name, BETA_CUSTOMER)
		self.assertEqual(lead.email, BETA_USER)
		self.assertEqual(lead.mobile_number, f"+91{MOBILE}")

	def test_the_lead_is_listed_with_the_borrowers_other_enquiries(self):
		reference = self.ask(BETA_USER)["reference"]

		self.assertIn(reference, [lead.name for lead in leads_for_login()])

	def test_a_login_with_several_customers_must_name_one(self):
		# User.mobile_no is unique and Beta already holds MOBILE.
		frappe.db.set_value("User", ALPHA_USER, "mobile_no", "9812345679")

		with self.assertRaises(frappe.ValidationError):
			self.ask(ALPHA_USER)

		reference = self.ask(ALPHA_USER, customer=ALPHA_OTHER_CUSTOMER)["reference"]
		self.assertEqual(frappe.db.get_value("Loan Lead", reference, "customer"), ALPHA_OTHER_CUSTOMER)

	def test_another_borrowers_customer_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.ask(BETA_USER, customer=ALPHA_CUSTOMER)

	def test_a_borrower_with_no_mobile_on_file_is_asked_to_add_one(self):
		frappe.db.set_value("User", BETA_USER, "mobile_no", None)

		with self.assertRaises(frappe.ValidationError):
			self.ask(BETA_USER)

	def test_a_product_that_is_not_offered_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.ask(BETA_USER, loan_product="No Such Product")

	def test_the_form_offers_only_the_logins_own_customers(self):
		frappe.set_user(ALPHA_USER)
		offered = [row["value"] for row in get_new_application_page()["applicants"]]

		self.assertIn(ALPHA_CUSTOMER, offered)
		self.assertIn(ALPHA_OTHER_CUSTOMER, offered)
		self.assertNotIn(BETA_CUSTOMER, offered)

	def test_the_form_starts_from_the_last_answers(self):
		self.ask(BETA_USER, income=60000, proposed_tenure=24)
		frappe.local.form_dict = frappe._dict()

		(beta,) = get_new_application_page()["applicants"]

		self.assertTrue(beta["has_mobile"])
		self.assertEqual(beta["answers"]["income"], 60000)
		self.assertEqual(beta["answers"]["proposed_tenure"], 24)

	def test_converting_it_keeps_the_borrowers_customer(self):
		reference = self.ask(BETA_USER)["reference"]
		frappe.set_user("Administrator")

		# Captured, not saved, to skip everything else Loan Application.validate demands.
		with patch.object(Document, "save", autospec=True) as save:
			convert_to_loan_application(frappe.get_doc("Loan Lead", reference))

		application = save.call_args.args[0]
		self.assertEqual(application.applicant_type, "Customer")
		self.assertEqual(application.applicant, BETA_CUSTOMER)


class TestPortalSignUp(LendingTestSuite):
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

		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()
		super().tearDown()

	def apply_as(self, email, mobile, **overrides):
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

	def open_account(self, offer, email=None, verified=True):
		frappe.local.form_dict = frappe._dict(
			{
				"token": offer["account_token"],
				"email": email or frappe.db.get_value("Loan Lead", offer["reference"], "email"),
				"otp": "123456",
			}
		)
		with patch("lending.portal.login.telephony_otp") as telephony:
			telephony.return_value.verify_otp.return_value = {"verified": verified}
			return create_account()

	def test_a_company_is_recorded_as_one(self):
		offer = self.apply_as(
			COMPANY_EMAIL,
			"9812340101",
			applicant_type="Business",
			company_name="Test Traders Pvt Ltd",
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
		# Not None: frappe fills a None Select with its first option, "Salaried".
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

	def test_an_account_is_opened_and_joined_to_a_customer(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340104")
		self.open_account(offer)

		self.assertTrue(frappe.db.exists("User", PERSON_EMAIL))
		self.assertIn("Customer", frappe.get_roles(PERSON_EMAIL))

		customer = customer_for_email(PERSON_EMAIL)
		self.assertTrue(customer)

		joined = [row.user for row in frappe.get_doc("Customer", customer).portal_users]
		self.assertIn(PERSON_EMAIL, joined)

	def existing_customer(self, name, email):
		frappe.set_user("Administrator")
		customer = create_customer(name, "Individual", email, "")
		frappe.set_user("Guest")

		return customer

	def portal_users(self, customer):
		return [row.user for row in frappe.get_doc("Customer", customer).portal_users]

	def test_a_signup_joins_the_customer_whose_own_address_it_is(self):
		customer = self.existing_customer("_Test Portal Existing Borrower", PERSON_EMAIL)

		self.open_account(self.apply_as(PERSON_EMAIL, "9812340120"))

		self.assertEqual(self.portal_users(customer), [PERSON_EMAIL])

	def test_a_signup_does_not_join_a_customer_it_is_only_a_contact_of(self):
		customer = self.existing_customer("_Test Portal Holdings", COMPANY_EMAIL)
		frappe.set_user("Administrator")
		clerk = frappe.new_doc("Contact")
		clerk.first_name = "Clerk"
		clerk.append("email_ids", {"email_id": PERSON_EMAIL, "is_primary": 1})
		clerk.append("links", {"link_doctype": "Customer", "link_name": customer})
		clerk.insert(ignore_permissions=True)
		frappe.set_user("Guest")

		self.open_account(self.apply_as(PERSON_EMAIL, "9812340121"))

		self.assertEqual(self.portal_users(customer), [])

	def test_a_signup_does_not_join_a_customer_someone_already_logs_in_to(self):
		customer = self.existing_customer("_Test Portal Claimed Borrower", PERSON_EMAIL)
		frappe.set_user("Administrator")
		make_website_user(COMPANY_EMAIL)
		link_portal_user(customer, COMPANY_EMAIL)
		frappe.set_user("Guest")

		self.open_account(self.apply_as(PERSON_EMAIL, "9812340122"))

		self.assertEqual(self.portal_users(customer), [COMPANY_EMAIL])

	def test_a_signup_does_not_join_either_customer_sharing_an_address(self):
		first = self.existing_customer("_Test Portal Shared One", PERSON_EMAIL)
		second = self.existing_customer("_Test Portal Shared Two", PERSON_EMAIL)

		self.open_account(self.apply_as(PERSON_EMAIL, "9812340123"))

		self.assertEqual(self.portal_users(first), [])
		self.assertEqual(self.portal_users(second), [])

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

		lead = leads_for_login()[0]
		self.assertEqual(lead.name, offer["reference"])

		with patch("lending.portal.applications.default_application", return_value=None):
			payload = get_application_detail()

		self.assertIs(payload["has_application"], True)
		self.assertEqual(payload["reference"], "Enquiry {0}".format(offer["reference"]))
		self.assertEqual(payload["steps"][0]["code"], "done")

	def test_a_converted_enquiry_gives_way_to_its_application(self):
		lead = frappe._dict(name="LN-LEAD-CONVERTED")

		with patch("lending.portal.core.leads_for_login", return_value=[lead]):
			self.assertEqual(open_lead(), lead)

			with patch("frappe.get_all", return_value=[lead.name]):
				self.assertIsNone(open_lead())

	def test_an_account_needs_a_token(self):
		self.apply_as(PERSON_EMAIL, "9812340106")
		frappe.local.form_dict = frappe._dict({"email": PERSON_EMAIL, "otp": "123456"})

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

	def test_a_desk_users_address_looks_like_a_new_one(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", DESK_EMAIL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": DESK_EMAIL,
					"first_name": "Desk",
					"send_welcome_email": 0,
					"user_type": "System User",
					# Without a desk role, User saves itself as a Website User.
					"roles": [{"role": "Loan Manager"}],
				}
			).insert(ignore_permissions=True)
		frappe.set_user("Guest")
		offer = self.apply_as(PERSON_EMAIL, "9812340114")

		frappe.local.form_dict = frappe._dict({"token": offer["account_token"], "email": DESK_EMAIL})
		with patch("lending.portal.login.telephony_otp") as telephony:
			self.assertTrue(send_account_code()["sent"])
			telephony.return_value.send_otp.assert_not_called()

		self.assertFalse(self.open_account(offer, email=DESK_EMAIL, verified=False)["verified"])

	def test_two_borrowers_can_share_a_mobile_number(self):
		self.open_account(self.apply_as(PERSON_EMAIL, "9812340110"))
		self.open_account(
			self.apply_as(
				COMPANY_EMAIL, "9812340110", applicant_type="Business", company_name="Test Traders Pvt Ltd"
			)
		)

		self.assertTrue(frappe.db.exists("User", COMPANY_EMAIL))
		self.assertFalse(frappe.db.get_value("User", COMPANY_EMAIL, "mobile_no"))

	def test_an_account_is_opened_without_a_password(self):
		self.open_account(self.apply_as(PERSON_EMAIL, "9812340110"))

		auth = frappe.qb.Table("__Auth")
		stored = (
			frappe.qb.from_(auth)
			.select(auth.name)
			.where((auth.doctype == "User") & (auth.name == PERSON_EMAIL) & (auth.fieldname == "password"))
			.run()
		)
		self.assertFalse(stored)

	def test_a_code_is_sent_to_the_email_given(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340113")
		frappe.local.form_dict = frappe._dict({"token": offer["account_token"], "email": COMPANY_EMAIL})

		with patch("lending.portal.login.telephony_otp") as telephony:
			send_account_code()
			telephony.return_value.send_otp.assert_called_once()

		self.assertEqual(telephony.return_value.send_otp.call_args.args[0], COMPANY_EMAIL)

	def test_a_wrong_code_opens_no_account_and_can_be_retried(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340112")

		self.assertFalse(self.open_account(offer, verified=False)["verified"])
		self.assertFalse(frappe.db.exists("User", PERSON_EMAIL))

		self.open_account(offer)
		self.assertTrue(frappe.db.exists("User", PERSON_EMAIL))

	def test_a_changed_email_moves_the_lead_with_it(self):
		offer = self.apply_as(PERSON_EMAIL, "9812340114")
		self.open_account(offer, email=COMPANY_EMAIL)

		self.assertTrue(frappe.db.exists("User", COMPANY_EMAIL))
		self.assertEqual(frappe.db.get_value("Loan Lead", offer["reference"], "email"), COMPANY_EMAIL)

	def test_converting_a_lead_reuses_the_borrowers_customer(self):
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
	# PageDoesNotExistError, not PermissionError: only the first renders as a 404.

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
		super().tearDown()

	def test_portal_off_hides_every_signed_in_page(self):
		set_portal_switches(0, 0)

		self.assertRaises(frappe.PageDoesNotExistError, get_portal_customers)

	def test_portal_off_hides_the_public_pages(self):
		set_portal_switches(0, 0)

		self.assertRaises(frappe.PageDoesNotExistError, get_apply_page)
		self.assertRaises(frappe.PageDoesNotExistError, get_track_page)

	def test_portal_off_closes_the_endpoints_that_write(self):
		set_portal_switches(0, 0)
		frappe.set_user("Guest")

		self.assertRaises(frappe.PageDoesNotExistError, send_mobile_code)
		self.assertRaises(frappe.PageDoesNotExistError, submit_lead)
		self.assertRaises(frappe.PageDoesNotExistError, create_account)

	def test_public_apply_off_leaves_the_signed_in_portal_serving(self):
		set_portal_switches(1, 0)

		self.assertRaises(frappe.PageDoesNotExistError, get_apply_page)
		self.assertRaises(frappe.PageDoesNotExistError, submit_lead)

		# The tracker follows the portal switch alone: desk-raised leads still need it.
		self.assertTrue(get_track_page()["heading"])

		self.assertIsInstance(get_portal_customers(), list)

	def test_a_product_not_shown_on_the_portal_is_not_offered(self):
		show_product_on_portal(PRODUCT, 0)

		self.assertNotIn(PRODUCT, offered_products("Individual"))
		self.assertNotIn(PRODUCT, offered_products("Business"))

	def test_a_product_not_shown_on_the_portal_cannot_be_applied_for(self):
		show_product_on_portal(PRODUCT, 0)

		self.assertRaises(frappe.ValidationError, read_product, PRODUCT, 100000)

	def test_a_product_shown_on_the_portal_is_offered_and_accepted(self):
		self.assertIn(PRODUCT, offered_products("Individual"))
		self.assertIn(PRODUCT, offered_products("Business"))
		self.assertEqual(read_product(PRODUCT, 100000)["name"], PRODUCT)
		self.assertEqual(read_product(PRODUCT, 100000, "Business")["name"], PRODUCT)

	def test_a_business_product_is_offered_to_companies_alone(self):
		offer_product_to(PRODUCT, "Business")

		self.assertIn(PRODUCT, offered_products("Business"))
		self.assertNotIn(PRODUCT, offered_products("Individual"))

	def test_a_person_cannot_apply_for_a_business_product(self):
		offer_product_to(PRODUCT, "Business")

		self.assertRaises(frappe.ValidationError, read_product, PRODUCT, 100000, "Individual")
		self.assertEqual(read_product(PRODUCT, 100000, "Business")["name"], PRODUCT)

	def test_portal_off_takes_every_page_out_of_the_route_table(self):
		# A refusal during render is a 404 page with a 200 status; only unpublishing gives a real 404.
		set_portal_switches(0, 0)

		self.assertEqual(published_portal_routes(), set())

	def test_public_apply_off_takes_only_the_apply_page_out(self):
		set_portal_switches(1, 0)
		routes = published_portal_routes()

		self.assertNotIn(APPLY_ROUTE, routes)
		self.assertIn("/track", routes)
		self.assertIn("/overview", routes)

	def test_switching_the_portal_back_on_restores_every_page(self):
		before = published_portal_routes()
		set_portal_switches(0, 0)
		set_portal_switches(1, 1)

		self.assertEqual(published_portal_routes(), before)


class TestPortalBranding(LendingTestSuite):
	def tearDown(self):
		set_branding()
		frappe.local.form_dict = frappe._dict()
		super().tearDown()

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
		set_branding(portal_brand_name="Ganges Finance", portal_logo="/files/ganges.png")
		payload = brand_payload()

		self.assertEqual(payload["brand_logo"], "/files/ganges.png")
		self.assertEqual(payload["show_wordmark"], 0)
		# Still sent: it is the logo's alt text and the PDFs' fallback.
		self.assertEqual(payload["brand_name"], "Ganges Finance")

	def test_the_public_pages_carry_the_brand_too(self):
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
		tokens = brand_tokens("#004c8f", "#ed232a")

		self.assertEqual(tokens["--portal-primary"], "#004c8f")
		self.assertEqual(tokens["--portal-action"], "#ed232a")
		self.assertEqual(tokens["--portal-action-ink"], "#ffffff")

	def test_without_a_secondary_colour_the_buttons_take_the_primary(self):
		tokens = brand_tokens("#800000", None)

		self.assertEqual(tokens["--portal-action"], "#800000")

	def test_a_secondary_colour_alone_paints_only_the_buttons(self):
		style = brand_style(None, "#ed232a")

		self.assertIn("--portal-action: #ed232a;", style)
		self.assertNotIn("portal-header", style)
		self.assertNotIn("bg-surface-sidebar", style)

	def test_a_light_colour_carries_dark_ink_and_a_saturated_one_white(self):
		tokens = brand_tokens("#019eec", "#ffb600")

		self.assertEqual(tokens["--portal-action-ink"], "#171717")
		self.assertEqual(tokens["--portal-primary-ink"], "#ffffff")

	def test_a_saturated_orange_carries_white_where_wcag_would_hand_it_black(self):
		self.assertEqual(brand_tokens("#ef6f21", None)["--portal-primary-ink"], "#ffffff")
		self.assertEqual(brand_tokens("#ff9f1c", None)["--portal-primary-ink"], "#171717")

	def test_a_header_button_takes_the_secondary_only_where_it_stands_out(self):
		self.assertEqual(brand_tokens("#004c8f", "#ed232a")["--portal-header-action"], "#ed232a")
		self.assertEqual(brand_tokens("#292075", "#00b5ef")["--portal-header-action"], "#171717")

	def test_the_primary_colour_tints_the_sidebar_and_nothing_beside_it(self):
		style = brand_style("#004b8e", "#ed232a")

		self.assertIn(".borrower-portal .bg-surface-sidebar { --surface-sidebar: var(--portal-primary-soft);", style)
		self.assertNotIn(":root { --surface", style)

	def test_the_header_is_a_wash_of_the_primary_colour_in_frappe_uis_own_greys(self):
		style = brand_style("#004b8e", "#ed232a")

		self.assertIn(".borrower-portal .portal-header { background-color: var(--portal-primary-soft);", style)
		self.assertNotIn("--ink-gray-9", style)

	def test_a_done_step_is_a_wash_of_the_primary_with_a_tick_that_can_be_seen(self):
		hdfc = brand_tokens("#004b8e", None)
		self.assertEqual(hdfc["--portal-primary-soft"], "#e0e9f1")
		self.assertEqual(hdfc["--portal-primary-deep"], "#004b8e")

		canara = brand_tokens("#019eec", None)
		tick = contrast(channels(canara["--portal-primary-deep"]), channels(canara["--portal-primary-soft"]))
		self.assertGreaterEqual(tick, 3.0)
		self.assertNotEqual(canara["--portal-primary-deep"], "#019eec")

	def test_the_borrowers_initial_is_a_white_disc_on_the_rails_wash(self):
		style = brand_style("#004b8e", None)

		self.assertIn(".borrower-portal .portal-avatar { --surface-gray-2: var(--surface-elevation-1);", style)
		self.assertNotIn("portal-avatar", brand_style(None, "#ed232a"))

	def test_grey_buttons_and_table_bands_wear_a_wash_of_the_secondary(self):
		style = brand_style("#004c8f", "#ed232a")

		# .portal-plain (the statement's period shortcuts) stays grey.
		self.assertIn(
			'.borrower-portal button.bg-surface-gray-2:not(.portal-plain):not([role="combobox"]) { background-color: var(--portal-action-soft);',
			style,
		)
		self.assertEqual(brand_tokens("#004c8f", "#ed232a")["--portal-action-soft"], "#fde5e5")

	def test_a_label_on_a_wash_reads_as_body_text_even_while_pressed(self):
		for secondary in ("#ed232a", "#ffb600", "#00b5ef"):
			tokens = brand_tokens("#004c8f", secondary)
			label = channels(tokens["--portal-action-deep"])
			for ground in ("--portal-action-soft", "--portal-action-soft-hover", "--portal-action-soft-active"):
				self.assertGreaterEqual(contrast(label, channels(tokens[ground])), 4.5, (secondary, ground))

	def test_the_footer_wears_the_headers_wash(self):
		style = brand_style("#004b8e", None)

		self.assertIn(".borrower-portal .portal-footer { background-color: var(--portal-primary-soft);", style)

	def test_only_a_hex_colour_reaches_the_stylesheet(self):
		self.assertEqual(brand_style("red; } body { display: none", "</style><script>"), "")
		self.assertIn("--portal-primary: #aabbcc;", brand_style("ABC", None))

	def test_the_style_reads_only_tokens_the_portal_stylesheet_defines(self):
		sheets = glob.glob(frappe.get_app_path("studio", "public", "frontend", "assets", "*.css"))
		if not sheets:
			self.skipTest("Studio's frontend is not built")

		defined = set()
		for sheet in sheets:
			with open(sheet) as css:
				defined.update(re.findall(r"(--[\w-]+):", css.read()))

		used = set(re.findall(r"var\((--[\w-]+)\)", brand_style("#004b8e", "#ed232a")))
		self.assertEqual({token for token in used if not token.startswith("--portal-")} - defined, set())


class TestPortalPresets(LendingTestSuite):
	def test_every_preset_button_label_reads_in_both_modes(self):
		for name, preset in PRESETS.items():
			light = channels(preset.secondary)
			self.assertGreaterEqual(contrast(light, channels(ink_for(light))), 4.5, name)

			dark = channels(preset.dark_secondary)
			ink = channels(preset.dark_ink or ink_for(dark))
			self.assertGreaterEqual(contrast(dark, ink), 4.5, name)

	def test_every_preset_stands_out_on_the_dark_ground(self):
		for name, preset in PRESETS.items():
			for colour in (preset.dark_primary, preset.dark_secondary):
				self.assertGreaterEqual(contrast(channels(colour), DARK_GROUND), 3.0, (name, colour))

	def test_no_preset_is_red(self):
		# Red marks danger: errors, failed payments, overdue EMIs. frappe-ui red sits at 18° to 27°.
		for name, preset in PRESETS.items():
			for colour in preset[:4]:
				hue = oklch_hue(colour)
				self.assertFalse(hue is not None and 10 <= hue <= 32, (name, colour))

	def test_a_preset_overrides_the_colour_fields(self):
		preset = resolve("Forest", "#004c8f", "#ed232a")

		self.assertEqual((preset.primary, preset.secondary), ("#085e35", "#14804d"))

	def test_custom_an_unknown_or_no_theme_keeps_the_colour_fields(self):
		for theme in ("Custom", "Sunset", None, ""):
			preset = resolve(theme, "#004c8f", "#ed232a")

			self.assertEqual((preset.primary, preset.secondary), ("#004c8f", "#ed232a"), theme)
			self.assertIsNone(preset.dark_primary, theme)

	def test_a_preset_paints_its_own_dark_pair_after_the_light_one(self):
		style = brand_style(*PRESETS["Forest"])

		self.assertIn('[data-theme="dark"] { --portal-primary: #369768;', style)
		self.assertLess(style.index(":root {"), style.index('[data-theme="dark"] {'))

	def test_custom_colours_get_a_dark_pair_lifted_off_the_dark_ground(self):
		dark = dark_tokens("#004b8e", "#ed232a", None, None, None)

		for token in ("--portal-primary", "--portal-action"):
			self.assertGreaterEqual(contrast(channels(dark[token]), DARK_GROUND), 3.0, token)

	def test_a_banks_dark_colour_is_lifted_only_as_far_as_it_needs(self):
		# HDFC navy and SBI indigo.
		for colour in ("#004b8e", "#292075"):
			lighter = channels(lift(channels(colour), DARK_GROUND, 3.0))

			self.assertGreaterEqual(contrast(lighter, DARK_GROUND), 3.0, colour)
			self.assertLess(contrast(lighter, DARK_GROUND), 3.5, colour)

	def test_a_colour_that_already_stands_out_is_not_lifted(self):
		# Canara blue.
		self.assertEqual(lift(channels("#019eec"), DARK_GROUND, 3.0), "#019eec")

	def test_dark_header_buttons_keep_the_brand_and_their_labels_read(self):
		for name, preset in PRESETS.items():
			dark = dark_tokens(*preset)
			button = channels(dark["--portal-header-action"])

			self.assertNotEqual(dark["--portal-header-action"], "#ffffff", name)
			self.assertGreaterEqual(contrast(button, channels(dark["--portal-primary-soft"])), 3.0, name)
			self.assertGreaterEqual(contrast(button, channels(dark["--portal-header-action-ink"])), 4.5, name)

	def test_a_pressed_dark_button_reads_at_least_as_well_as_a_resting_one(self):
		for name, preset in PRESETS.items():
			dark = dark_tokens(*preset)
			ink = channels(dark["--portal-action-ink"])
			resting = contrast(channels(dark["--portal-action"]), ink)

			for state in ("--portal-action-hover", "--portal-action-active"):
				self.assertGreaterEqual(contrast(channels(dark[state]), ink), resting, (name, state))

	def test_dark_labels_on_a_wash_read_as_body_text(self):
		for name, preset in PRESETS.items():
			dark = dark_tokens(*preset)
			label = channels(dark["--portal-action-deep"])

			for ground in ("--portal-action-soft", "--portal-action-soft-hover", "--portal-action-soft-active"):
				self.assertGreaterEqual(contrast(label, channels(dark[ground])), 4.5, (name, ground))

	def test_only_a_hex_colour_reaches_the_stylesheet_through_a_preset_path(self):
		preset = resolve("Custom", "red; } body { display: none", "</style><script>")

		self.assertEqual(brand_style(preset.primary, preset.secondary), "")


class TestPortalFooter(LendingTestSuite):
	def tearDown(self):
		set_footer()
		set_branding()
		super().tearDown()

	def test_an_unwritten_notice_names_the_lender_and_the_year(self):
		set_branding(portal_brand_name="Ganges Finance")
		set_footer()

		self.assertEqual(
			copyright_note(), f"Copyright © {getdate(nowdate()).year} Ganges Finance. All rights reserved."
		)

	def test_an_unnamed_portal_puts_our_name_in_its_own_notice(self):
		set_branding()
		set_footer()

		self.assertIn(DEFAULT_BRAND_NAME, copyright_note())

	def test_a_company_that_ends_in_a_stop_does_not_get_two(self):
		set_branding(portal_brand_name="Ganges Finance Ltd.")
		set_footer()

		self.assertIn("Ganges Finance Ltd. All rights reserved.", copyright_note())

	def test_a_lender_writes_its_own_notice(self):
		set_footer(notice="© Ganges Finance. A Ganges Group company.")

		self.assertEqual(copyright_note(), "© Ganges Finance. A Ganges Group company.")

	def test_a_written_notice_still_gets_this_year(self):
		set_footer(notice="© {year} Ganges Finance.")

		self.assertEqual(copyright_note(), f"© {getdate(nowdate()).year} Ganges Finance.")

	def test_a_notice_carrying_a_stray_brace_is_text_and_not_an_error(self):
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
		set_footer(links=(("Privacy Policy", "/borrower/privacy-policy"),), support="care@ganges.example.com")

		self.assertEqual(
			footer_links()[-1],
			{"footer_label": "Contact us", "footer_href": "mailto:care@ganges.example.com"},
		)

	def test_no_address_means_no_contact_us(self):
		set_footer(links=(("Privacy Policy", "/borrower/privacy-policy"),))

		self.assertEqual([link["footer_label"] for link in footer_links()], ["Privacy Policy"])

	def test_no_links_and_no_address_leaves_the_row_empty_rather_than_broken(self):
		set_footer()

		self.assertEqual(footer_links(), [])
		self.assertEqual(shell_payload("Loans", "Apply", [])["footer_links"], [])

	def test_a_row_missing_its_destination_is_not_a_link(self):
		set_footer(links=(("Privacy Policy", ""),))

		self.assertEqual(footer_links(), [])

	def test_the_footer_reaches_the_frame_every_page_wears(self):
		set_branding(portal_brand_name="Ganges Finance")
		set_footer(links=(("Privacy Policy", "/borrower/privacy-policy"),))
		payload = shell_payload("Loans", "Apply", [])

		self.assertIn("Ganges Finance", payload["copyright_note"])
		self.assertEqual(payload["footer_links"][0]["footer_label"], "Privacy Policy")

class TestPortalMenu(LendingTestSuite):
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
		frappe.local.request = frappe._dict(path=route)

		return {row["nav_title"]: row["nav_current"] for row in nav_items()}

	def test_the_menu_is_the_one_declared_in_hooks(self):
		rows = nav_items()

		self.assertEqual(
			[(row["nav_title"], row["nav_route"]) for row in rows],
			[(item["title"], item["route"]) for item in self.declared()],
		)

	def test_another_portals_rows_are_left_to_it(self):
		# get_portal_sidebar_items answers for the whole site, ERPNext's portal included.
		routes = {row["nav_route"] for row in nav_items()}

		self.assertNotIn("/orders", routes)
		self.assertNotIn("/invoices", routes)

	def test_the_page_being_served_is_the_row_that_lights(self):
		marks = self.serving("/borrower-portal/statement")

		self.assertEqual(marks["Statement of account"], "page")
		self.assertEqual(marks["Account overview"], "false")
		self.assertEqual([*marks.values()].count("page"), 1)

	def test_a_detail_page_lights_the_list_it_belongs_to(self):
		self.assertEqual(self.serving("/borrower-portal/loan/LOAN-0001")["Loan accounts"], "page")
		self.assertEqual(
			self.serving("/borrower-portal/application/LN-APP-0001")["Application"], "page"
		)

	def test_a_list_is_not_swallowed_by_the_section_beside_it(self):
		marks = self.serving("/borrower-portal/applications")

		self.assertEqual(marks["Application"], "page")
		self.assertEqual([*marks.values()].count("page"), 1)

	def test_off_a_request_the_menu_still_comes_out(self):
		frappe.local.request = None
		marks = {row["nav_title"]: row["nav_current"] for row in nav_items()}

		self.assertEqual(len(marks), len(self.declared()))
		self.assertNotIn("page", marks.values())

class TestPortalRail(LendingTestSuite):
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

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()
		super().tearDown()

	def search(self, query: str) -> dict:
		frappe.set_user(ALPHA_USER)
		frappe.local.form_dict = frappe._dict({"q": query})

		return find()

	def test_the_search_page_is_gone(self):
		self.assertNotIn("/search", published_portal_routes())

	def test_the_notifications_page_is_gone(self):
		self.assertNotIn("/notifications", published_portal_routes())

	def test_a_product_finds_loans_and_nothing_that_is_not_one(self):
		# Asserts on the answer, not the fixture: the DB is not rolled back, so loans pile up.
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
		results = self.search(self.beta_loan)["results"]

		self.assertEqual(results, [])

	def test_every_word_has_to_match(self):
		self.assertTrue(self.search(PRODUCT)["results"])
		self.assertEqual(self.search(f"{PRODUCT} nothing-matches-this")["results"], [])

	def test_an_empty_box_opens_holding_somewhere_to_go(self):
		payload = self.search("")

		self.assertEqual(
			[row["url"] for row in payload["results"]],
			[item["route"] for item in frappe.get_hooks("portal_menu_items")][:RESULT_LIMIT],
		)
		self.assertEqual({row["kind"] for row in payload["results"]}, {"Page"})
		self.assertEqual(payload["note"], "")

	def test_a_page_is_findable_by_name_like_anything_else(self):
		results = self.search("interest certificate")["results"]

		self.assertEqual(
			[(row["kind"], row["url"]) for row in results], [("Page", "/borrower-portal/certificate")]
		)

	def test_a_search_that_matches_everything_is_cut_down(self):
		self.assertIn(str(RESULT_LIMIT), results_note("loan", RESULT_LIMIT + 10))
		self.assertIn(str(RESULT_LIMIT + 10), results_note("loan", RESULT_LIMIT + 10))

	def test_the_palette_never_answers_past_its_limit(self):
		self.assertLessEqual(len(self.search(PRODUCT)["results"]), RESULT_LIMIT)

	def test_a_draft_application_is_work_waiting_on_the_borrower(self):
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
		rows = attention_rows([], [{"product": PRODUCT, "detail": "", "date": "z", "amount": "1"}])

		self.assertEqual(rows[0]["url"], "/borrower-portal/loans")

	def test_the_borrowers_own_list_is_capped_and_says_how_long_it_really_is(self):
		frappe.set_user(ALPHA_USER)
		payload = get_notifications()

		self.assertLessEqual(len(payload["attention"]), ATTENTION_LIMIT)
		for row in payload["attention"]:
			self.assertTrue(row["url"].startswith("/borrower-portal/"))
		self.assertTrue(
			payload["attention_note"] == "Nothing to do" or "waiting on you" in payload["attention_note"]
		)

	def test_another_borrowers_work_is_not_on_this_ones_list(self):
		frappe.set_user(BETA_USER)
		urls = [row["url"] for row in get_notifications()["attention"]]

		self.assertNotIn(f"/borrower-portal/application/{self.alpha_application}", urls)

	def test_what_has_happened_comes_out_in_the_same_shape_as_what_is_waiting(self):
		rows = activity_rows(
			[{"title": "Payment made", "sub": PRODUCT, "date": "12 Sep 2026", "amount": "1,000"}]
		)

		self.assertEqual(
			rows,
			[
				{
					"title": "Payment made",
					"note": PRODUCT,
					"when": "1,000 · 12 Sep 2026",
					"url": "/borrower-portal/statement",
				}
			],
		)
		self.assertEqual(
			set(rows[0]),
			set(attention_rows([], [{"product": "x", "detail": "y", "date": "z", "amount": "1"}])[0]),
		)

	def test_every_row_says_whether_it_has_been_read(self):
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
		frappe.set_user(ALPHA_USER)
		frappe.defaults.set_user_default(READ_KEY, json.dumps(["stale-key-from-before"]))
		mark_all_as_read()

		self.assertNotIn("stale-key-from-before", read_keys())

	def test_a_borrower_whose_marks_are_unreadable_is_not_an_error(self):
		frappe.set_user(ALPHA_USER)
		frappe.defaults.set_user_default(READ_KEY, "not json")

		self.assertEqual(read_keys(), set())
		self.assertTrue(get_notifications()["activity_note"])


class TestPortalSummaryStrip(LendingTestSuite):
	def blocks(self, node) -> list[dict]:
		found = [node]
		for child in node.get("children") or []:
			found.extend(self.blocks(child))

		return found

	def test_a_borrower_with_nothing_in_progress_is_not_shown_an_empty_card(self):
		empty = application_lead([])

		self.assertEqual(empty["application_stage"], "")
		self.assertEqual(empty["application_headline"], "")
		self.assertEqual(empty["application_note"], "Nothing in progress")

	def test_the_card_names_the_newest_application_and_says_how_many_more(self):
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
			"initiated_date": "01 Jan 2026",
			"note": "",
		}

	def test_the_card_opens_the_loan_once_the_application_has_become_one(self):
		under_review = application_lead([self.application("Home Loan")])
		sanctioned = application_lead([self.application("Home Loan", loan="LOAN-1")])

		self.assertEqual(under_review["application_url"], "/borrower-portal/application/APP-1")
		self.assertEqual(sanctioned["application_url"], "/borrower-portal/loan/LOAN-1")

	def test_a_card_with_nothing_in_progress_offers_nowhere_to_go(self):
		self.assertEqual(application_lead([])["application_url"], "")

	def test_an_open_enquiry_leads_the_card_until_it_is_an_application(self):
		lead = frappe._dict(
			name="LN-LEAD-1",
			loan_product="Education Loan",
			prequalification_status="",
			creation="2026-09-26 10:00:00",
		)
		card = enquiry_lead(lead)

		self.assertEqual(card["application_headline"], "Education Loan")
		self.assertEqual(card["application_date"], "26 Sep 2026")
		self.assertEqual(card["application_stage_tone"], "info")
		self.assertEqual(card["application_note"], "Your loan application process has started")
		self.assertEqual(card["application_url"], "/borrower-portal/applications")
		self.assertEqual(enquiry_lead(None), application_lead([]))

	def test_a_declined_enquiry_does_not_say_the_process_has_started(self):
		lead = frappe._dict(
			name="LN-LEAD-2",
			loan_product="Education Loan",
			prequalification_status="Not Pre-Qualified",
			creation="2026-09-26 10:00:00",
		)
		card = enquiry_lead(lead)

		self.assertEqual(card["application_stage"], "Not taken forward")
		self.assertEqual(card["application_note"], "")

	def test_the_card_names_the_day_the_application_was_raised(self):
		lead = application_lead([self.application("Home Loan")])

		self.assertEqual(lead["application_date_label"], "Initiated")
		self.assertEqual(lead["application_date"], "01 Jan 2026")

	def test_the_sanctioned_amount_is_one_line_under_the_outstanding_figure(self):
		loans = [frappe._dict(status="Active", loan_amount=500000, disbursed_amount=300000)]
		line = build_summary(loans, [])["sanctioned_line"]

		self.assertIn(money(500000), line)
		self.assertIn(money(200000), line)

class TestPortalRanking(LendingTestSuite):
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

	def test_an_application_under_review_is_not_waiting_on_the_borrower(self):
		reviewing = dict(self.draft(), needs_borrower=False, stage="Under review")

		self.assertEqual(waiting_on_borrower([reviewing]), [])

	def test_a_draft_opens_where_it_is_cleared(self):
		rows = waiting_on_borrower([self.draft(), dict(self.draft(), needs_borrower=False)])

		self.assertEqual([row["url"] for row in rows], ["/borrower/application/APP-1"])
		self.assertEqual(rows[0]["note"], "Submit to start the review")

	def test_the_strip_leaves_the_payment_to_the_button(self):
		source = inspect.getsource(waiting_on_borrower)

		self.assertNotIn("schedule", source)
		self.assertNotIn(REPAYMENTS_ROUTE, source)

	def test_the_button_is_the_payment_page_either_way(self):
		quiet = next_action(due_soon=False)
		loud = next_action(due_soon=True)

		self.assertEqual(quiet["action_href"], REPAYMENTS_ROUTE)
		self.assertEqual(loud["action_href"], REPAYMENTS_ROUTE)
		self.assertEqual(quiet["action_label"], loud["action_label"])

	def test_the_button_only_insists_when_a_payment_is_near(self):
		self.assertEqual(next_action(due_soon=False)["action_urgent"], "0")
		self.assertEqual(next_action(due_soon=True)["action_urgent"], "1")

	def test_one_live_account_reads_its_standing_in_its_own_row(self):
		one = [frappe._dict(name="L-1", status="Disbursed")]
		two = [frappe._dict(name="L-1", status="Disbursed"), frappe._dict(name="L-2", status="Active")]

		self.assertEqual(account_status(one)["account_status"], "")
		self.assertEqual(account_status(two)["account_status"], "All accounts regular")

	def test_a_fully_drawn_loan_gets_progress_where_it_got_its_own_figure_back(self):
		drawn = standing_line(sanctioned=300000, undrawn=0, drawn=300000, repaid=50000)
		partly = standing_line(sanctioned=300000, undrawn=100000, drawn=200000, repaid=0)

		self.assertIn(money(50000), drawn)
		self.assertNotIn("sanctioned", drawn.lower())
		self.assertIn("undrawn", partly.lower())

	def test_nothing_sanctioned_still_says_nothing(self):
		self.assertEqual(standing_line(sanctioned=0, undrawn=0, drawn=0, repaid=0), "")

	def test_one_loans_instalments_stop_repeating_its_name(self):
		rows = name_once([self.instalment(), self.instalment()])

		self.assertEqual([row["sub"] for row in rows], ["", ""])
		self.assertEqual([row["title"] for row in rows], [row["detail"] for row in rows])

	def test_two_loans_keep_their_names_on_every_row(self):
		rows = name_once([self.instalment("Personal Loan"), self.instalment("Demand Loan")])

		self.assertEqual([row["title"] for row in rows], ["Personal Loan", "Demand Loan"])
		self.assertEqual([row["sub"] for row in rows], [row["detail"] for row in rows])

class TestPortalActivityList(LendingTestSuite):
	def test_an_event_from_today_is_not_told_in_hours(self):
		# Why days_ago, not pretty_date: pretty_date reads a posting date as midnight.
		self.assertEqual(days_ago(nowdate()), "Today")
		self.assertEqual(days_ago(add_days(nowdate(), -1)), "Yesterday")

	def test_how_long_ago_is_told_in_the_unit_that_fits(self):
		said = [days_ago(add_days(nowdate(), -days)) for days in (3, 8, 40, 400)]

		self.assertEqual(said, ["3 days ago", "1 week ago", "1 month ago", "1 year ago"])


class TestPortalDisbursementRequest(LendingTestSuite):
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

		frappe.set_user(ALPHA_USER)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()
		super().tearDown()

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

		frappe.set_user(ALPHA_USER)

	def tearDown(self):
		frappe.defaults.clear_user_default(CHOSEN_LOAN_KEY, ALPHA_USER)
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()
		super().tearDown()

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
		# Its own borrower: every setUp here gives Beta another loan and nothing rolls them back.
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


class TestPortalPrintFormats(LendingTestSuite):
	def test_install_creates_a_missing_layout(self):
		for name, _html in FORMATS:
			frappe.delete_doc("Print Format", name, force=True, ignore_permissions=True, ignore_missing=True)

		ensure_print_formats()

		for name, html in FORMATS:
			self.assertEqual(frappe.db.get_value("Print Format", name, "html"), html)

	def test_migrate_keeps_a_layout_the_lender_edited(self):
		ensure_print_formats()
		frappe.db.set_value("Print Format", STATEMENT_FORMAT, "html", "<p>Our own statement</p>")

		ensure_print_formats()

		self.assertEqual(frappe.db.get_value("Print Format", STATEMENT_FORMAT, "html"), "<p>Our own statement</p>")
