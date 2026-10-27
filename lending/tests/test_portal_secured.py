# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe

from lending.collateral.mutual_fund.sample import OTP, SampleRegistryAdapter
from lending.collateral.mutual_fund.test_mutual_fund import (
	ELSS,
	FLEXI_CAP,
	make_holding,
	setup_test_data,
)
from lending.loan_integrations.adapters import register
from lending.loan_integrations.sample_verification import (
	CONSENT_KEY,
	SampleBankVerificationAdapter,
	SampleESignAdapter,
	SampleKycAdapter,
	SamplePanAdapter,
)
from lending.portal import secured
from lending.portal.apply import VERIFICATION_PREFIX
from lending.tests.test_portal import make_portal_customer, make_website_user, set_portal_switches
from lending.tests.utils import LendingTestSuite

for adapter in (
	SampleRegistryAdapter,
	SamplePanAdapter,
	SampleKycAdapter,
	SampleBankVerificationAdapter,
	SampleESignAdapter,
):
	register(adapter)

USER = "_test-secured-borrower@example.com"
CUSTOMER = "_Test Secured Borrower"
OTHER_CUSTOMER = "_Test Loan Customer"
PRODUCT = "Stock Loan"
PAN = "BXRPR4821K"
MOBILE = "+919845012345"


def a_pdf(pages=1) -> bytes:
	"""A real, minimal PDF: Frappe reads an attachment to check it carries no JavaScript."""
	from io import BytesIO

	from pypdf import PdfWriter

	writer = PdfWriter()
	for _page in range(pages):
		writer.add_blank_page(width=72, height=72)
	buffer = BytesIO()
	writer.write(buffer)

	return buffer.getvalue()


def use_sample_providers(approval="Automatic"):
	settings = frappe.get_doc("Lending Settings")
	settings.mutual_fund_registry_adapter = SampleRegistryAdapter.key
	settings.portal_loan_approval = approval
	settings.portal_secured_loans = []
	settings.append("portal_secured_loans", {"collateral": "Mutual Funds", "loan_product": PRODUCT})
	settings.save()

	frappe.db.set_single_value(
		"Loan Origination Settings",
		{
			"pan_verification_adapter": SamplePanAdapter.key,
			"kyc_adapter": SampleKycAdapter.key,
			"bank_verification_adapter": SampleBankVerificationAdapter.key,
			"esign_adapter": SampleESignAdapter.key,
		},
	)


def post(method, **values):
	frappe.local.form_dict = frappe._dict(values)
	return getattr(secured, method)()


def page():
	frappe.local.form_dict = frappe._dict()
	return secured.get_secured_loan()


class SecuredJourneyTestSuite(LendingTestSuite):
	def setUp(self):
		setup_test_data()
		set_portal_switches(1, 1)
		use_sample_providers()
		make_website_user(USER)
		make_portal_customer(CUSTOMER, USER)
		frappe.db.set_value("Customer", CUSTOMER, "mobile_no", MOBILE)
		frappe.set_user(USER)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def verify_pan(self):
		self.assertTrue(post("verify_pan", pan=PAN)["ok"])

	def fetch_holdings(self):
		sent = post("send_holdings_otp", collateral="Mutual Funds")
		return post("fetch_holdings", collateral="Mutual Funds", request_id=sent["request_id"], otp=OTP)

	def holding(self, security):
		return next(row for row in page()["holdings"] if row["scheme"] == security)

	def start_application(self, security=FLEXI_CAP, amount=10000):
		row = self.holding(security)
		lines = frappe.as_json([{"holding": row["holding"], "units": row["pledgeable_units"]}])
		return post("start_application", collateral="Mutual Funds", lines=lines, loan_amount=amount, tenure=12)

	def complete_kyc(self):
		request = post("start_kyc")["redirect_url"].split("request=")[1]
		self.assertTrue(request)
		post("give_kyc_consent")
		self.assertTrue(post("complete_kyc")["ok"])

	def pledge(self):
		post("send_pledge_otp")
		self.assertTrue(post("confirm_pledge", otp=OTP)["ok"])

	def add_bank_account(self, account_number="50100234567812"):
		self.assertTrue(post("save_bank_account", account_number=account_number, ifsc="HDFC0001234")["ok"])

	def start_esign(self):
		with patch("lending.portal.secured.get_pdf", return_value=a_pdf()):
			answer = post("start_esign")
		self.assertIn("request=", answer["redirect_url"])

	def sign(self):
		self.add_bank_account()
		self.start_esign()
		self.assertTrue(post("give_esign_consent", otp=OTP)["ok"])
		return post("complete_esign")

	def walk_to_signing(self):
		self.verify_pan()
		self.fetch_holdings()
		self.start_application()
		self.complete_kyc()
		self.pledge()


class TestTheJourney(SecuredJourneyTestSuite):
	def test_a_borrower_reaches_an_open_loan_on_the_portal(self):
		self.walk_to_signing()
		self.assertTrue(self.sign()["opened"])

		journey = page()
		self.assertEqual(journey["current"], "loan")
		self.assertTrue(all(row["state"] == "done" for row in journey["steps"]))

		loan = frappe.get_doc("Loan", journey["loan"]["name"])
		self.assertEqual(loan.docstatus, 1)
		self.assertEqual(loan.applicant, CUSTOMER)
		assignment = frappe.get_doc("Loan Security Assignment", {"loan_application": loan.loan_application})
		self.assertEqual(assignment.status, "Pledged")
		self.assertTrue(assignment.securities[0].lien_reference)
		self.assertTrue(assignment.securities[0].mutual_fund_holding)

	def test_no_credit_bureau_report_is_pulled(self):
		self.walk_to_signing()
		self.sign()

		self.assertFalse(frappe.db.exists("Credit Bureau Report", {"applicant": CUSTOMER}))

	def test_staff_review_leaves_the_signed_application_for_staff(self):
		frappe.set_user("Administrator")
		use_sample_providers(approval="Staff Review")
		frappe.set_user(USER)

		self.walk_to_signing()
		self.assertFalse(self.sign()["opened"])

		journey = page()
		self.assertFalse(journey["loan"])
		self.assertEqual(journey["current"], "loan")
		self.assertEqual(frappe.db.get_value("Loan Application", journey["application"]["name"], "status"), "Open")


class TestWithdrawal(SecuredJourneyTestSuite):
	def open_loan(self):
		self.walk_to_signing()
		self.assertTrue(self.sign()["opened"])
		return page()["loan"]

	def test_a_withdrawal_is_paid_into_the_verified_account(self):
		loan = self.open_loan()
		self.assertTrue(post("withdraw", amount=6000)["ok"])

		paid = frappe.get_doc("Loan Disbursement", {"against_loan": loan["name"]})
		self.assertEqual(paid.docstatus, 1)
		self.assertEqual(paid.disbursed_amount, 6000)
		self.assertEqual(paid.bank_account, frappe.db.get_value("Loan Application", page()["application"]["name"], "bank_account"))
		self.assertEqual(frappe.db.get_value("Loan", loan["name"], "disbursed_amount"), 6000)

	def test_more_than_is_available_is_refused(self):
		loan = self.open_loan()

		with self.assertRaises(frappe.ValidationError):
			post("withdraw", amount=loan["available"] + 1)

	def test_staff_review_raises_a_draft_and_holds_the_next_request(self):
		loan = self.open_loan()
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Lending Settings", "portal_loan_approval", "Staff Review")
		frappe.set_user(USER)

		post("withdraw", amount=5000)

		self.assertEqual(frappe.db.get_value("Loan Disbursement", {"against_loan": loan["name"]}, "docstatus"), 0)
		self.assertTrue(page()["loan"]["pending_note"])
		with self.assertRaises(frappe.ValidationError):
			post("withdraw", amount=1000)


class TestUnitsToPledge(SecuredJourneyTestSuite):
	def setUp(self):
		super().setUp()
		self.verify_pan()
		self.fetch_holdings()

	def apply_for(self, units, security=FLEXI_CAP):
		lines = frappe.as_json([{"holding": self.holding(security)["holding"], "units": units}])
		return post("start_application", collateral="Mutual Funds", lines=lines, loan_amount=100, tenure=12)

	def test_only_the_chosen_units_are_pledged(self):
		self.apply_for(25)

		application = frappe.get_doc("Loan Application", page()["application"]["name"])
		self.assertEqual(sum(row.qty for row in application.proposed_pledges), 25)

	def test_more_units_than_can_be_pledged_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.apply_for(self.holding(FLEXI_CAP)["pledgeable_units"] + 1)

	def test_one_holding_split_over_lines_cannot_pass_its_limit(self):
		row = self.holding(FLEXI_CAP)
		half = row["pledgeable_units"] / 2 + 1
		lines = frappe.as_json([{"holding": row["holding"], "units": half}] * 2)

		with self.assertRaises(frappe.ValidationError):
			post("start_application", collateral="Mutual Funds", lines=lines, loan_amount=100, tenure=12)

	def test_units_come_from_the_oldest_unlocked_lots(self):
		elss = self.holding(ELSS)
		self.apply_for(elss["pledgeable_units"], security=ELSS)

		application = frappe.get_doc("Loan Application", page()["application"]["name"])
		self.assertEqual(sum(row.qty for row in application.proposed_pledges), elss["pledgeable_units"])
		self.assertTrue(all(row.purchase_date for row in application.proposed_pledges))


class TestTheStepsAreChecked(SecuredJourneyTestSuite):
	def test_holdings_need_a_verified_pan(self):
		with self.assertRaises(frappe.ValidationError):
			post("send_holdings_otp", collateral="Mutual Funds")

	def test_a_pledge_needs_kyc(self):
		self.verify_pan()
		self.fetch_holdings()
		self.start_application()

		with self.assertRaises(frappe.ValidationError):
			post("send_pledge_otp")

	def test_a_kyc_for_another_pan_is_refused(self):
		self.verify_pan()
		self.fetch_holdings()
		self.start_application()
		request = post("start_kyc")["redirect_url"].split("request=")[1]
		post("give_kyc_consent")
		key = f"{CONSENT_KEY}:{request}"
		frappe.cache.set_value(key, {**frappe.cache.get_value(key), "pan": "AAAAA1111A"})

		self.assertFalse(post("complete_kyc")["ok"])
		self.assertEqual(frappe.db.get_value("Borrower KYC", CUSTOMER, "kyc_status"), "Rejected")
		with self.assertRaises(frappe.ValidationError):
			post("send_pledge_otp")

	def test_a_wrong_otp_is_answered_not_raised(self):
		self.verify_pan()
		sent = post("send_holdings_otp", collateral="Mutual Funds")

		answer = post("fetch_holdings", collateral="Mutual Funds", request_id=sent["request_id"], otp="000000")

		self.assertFalse(answer["ok"])
		self.assertFalse(page()["holdings"])

	def test_a_loan_above_the_eligible_amount_is_refused(self):
		self.verify_pan()
		self.fetch_holdings()

		with self.assertRaises(frappe.ValidationError):
			self.start_application(amount=10**9)

	def test_a_pan_unlike_the_customers_is_refused(self):
		frappe.db.set_value("Customer", CUSTOMER, "tax_id", "AAAAA1111A")

		with self.assertRaises(frappe.ValidationError):
			post("verify_pan", pan=PAN)

	def test_the_signed_terms_cannot_change(self):
		frappe.set_user("Administrator")
		use_sample_providers(approval="Staff Review")
		frappe.set_user(USER)
		self.walk_to_signing()
		self.sign()

		with self.assertRaises(frappe.ValidationError):
			post("save_bank_account", account_number="50100999999999", ifsc="HDFC0001234")
		with self.assertRaises(frappe.ValidationError):
			post("start_esign")

	def test_the_borrower_can_read_the_letter(self):
		self.walk_to_signing()
		self.add_bank_account()
		self.start_esign()

		self.assertEqual(page()["esign"]["letter"], secured.LETTER_URL)
		secured.download_sanction_letter()
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))


class TestESign(SecuredJourneyTestSuite):
	def setUp(self):
		super().setUp()
		self.walk_to_signing()
		self.add_bank_account()

	def application(self):
		return frappe.get_doc("Loan Application", secured.journey_application(CUSTOMER))

	def test_coming_back_unsigned_is_not_signing(self):
		self.start_esign()

		self.assertFalse(post("complete_esign")["ok"])
		self.assertTrue(page()["esign"]["pending"])
		self.assertFalse(self.application().signed_on)

	def test_a_wrong_otp_on_the_providers_page_signs_nothing(self):
		self.start_esign()

		self.assertFalse(post("give_esign_consent", otp="000000")["ok"])
		self.assertFalse(post("complete_esign")["ok"])

	def test_a_signature_the_provider_refused_starts_over(self):
		self.start_esign()

		with patch.object(SampleESignAdapter, "fetch", return_value={"status": "Rejected"}):
			self.assertFalse(post("complete_esign")["ok"])

		self.assertFalse(page()["esign"]["pending"])
		with self.assertRaises(frappe.ValidationError):
			post("complete_esign")

	def test_the_providers_signed_copy_replaces_the_letter(self):
		# Not the letter's own bytes: Frappe hands back the existing file for identical content.
		with patch.object(SampleESignAdapter, "download", return_value=a_pdf(pages=2)):
			self.assertTrue(self.sign()["ok"])

		self.assertIn("signed-sanction-letter", self.application().sanction_letter)

	def test_a_new_bank_account_drops_the_unsigned_request(self):
		self.start_esign()
		self.add_bank_account("50100999999999")

		self.assertFalse(page()["esign"]["pending"])
		self.assertFalse(self.application().esign_reference)

	def test_the_sample_page_is_closed_with_a_real_provider(self):
		self.start_esign()
		frappe.db.set_single_value("Loan Origination Settings", "esign_adapter", "Digio eSign")

		with self.assertRaises(frappe.PermissionError):
			post("give_esign_consent", otp=OTP)

	def test_a_collateral_without_a_journey_cannot_be_applied_for(self):
		self.verify_pan()

		with self.assertRaises(frappe.ValidationError):
			post("send_holdings_otp", collateral="Gold")

		gold = next(row for row in page()["collaterals"] if row["value"] == "Gold")
		self.assertFalse(gold["available"])


class TestHoldings(SecuredJourneyTestSuite):
	def test_units_in_lock_in_cannot_be_pledged(self):
		self.verify_pan()
		self.fetch_holdings()

		elss = self.holding(ELSS)

		self.assertLess(elss["pledgeable_units"], float(elss["units"]))
		self.assertTrue(elss["note"])

	def test_pledged_unlocked_units_do_not_free_the_locked_ones(self):
		self.verify_pan()
		self.fetch_holdings()
		self.start_application(security=ELSS, amount=100)
		self.complete_kyc()
		self.pledge()

		self.assertEqual(self.holding(ELSS)["pledgeable_units"], 0)

	def test_another_borrowers_holding_cannot_be_pledged(self):
		self.verify_pan()
		self.fetch_holdings()
		frappe.set_user("Administrator")
		theirs = make_holding(FLEXI_CAP, applicant=OTHER_CUSTOMER, folio_number="99999999/99")
		frappe.set_user(USER)

		with self.assertRaises(frappe.PermissionError):
			post(
				"start_application",
				collateral="Mutual Funds",
				lines=frappe.as_json([{"holding": theirs, "units": 1}]),
				loan_amount=10,
				tenure=12,
			)


class TestRegistration(SecuredJourneyTestSuite):
	def test_an_unverified_email_cannot_claim_a_customer(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("Customer", OTHER_CUSTOMER, "email_id", "victim@example.com")
		token = frappe.generate_hash(length=32)
		frappe.cache.set_value(f"{VERIFICATION_PREFIX}:{token}", MOBILE, expires_in_sec=60)
		frappe.set_user("Guest")

		post("register", token=token, full_name="Mallory", email="victim@example.com")

		frappe.set_user("Administrator")
		self.assertFalse(frappe.get_doc("Customer", OTHER_CUSTOMER).portal_users)
		self.assertNotEqual(frappe.db.get_value("Customer", OTHER_CUSTOMER, "mobile_no"), MOBILE)
		self.assertTrue(frappe.db.exists("Portal User", {"parenttype": "Customer", "user": "victim@example.com"}))


class TestSettings(LendingTestSuite):
	def test_a_collateral_takes_one_loan_product(self):
		settings = frappe.get_doc("Lending Settings")
		settings.portal_secured_loans = []
		settings.append("portal_secured_loans", {"collateral": "Gold", "loan_product": PRODUCT})
		settings.append("portal_secured_loans", {"collateral": "Gold", "loan_product": PRODUCT})

		with self.assertRaises(frappe.ValidationError):
			settings.save()
