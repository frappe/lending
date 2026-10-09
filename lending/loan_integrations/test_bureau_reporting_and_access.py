# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import cint

from lending.loan_integrations import bureau, log
from lending.loan_integrations.adapters import adapter_choices, register, registry
from lending.loan_integrations.base import IntegrationError
from lending.loan_integrations.bureau import BureauAdapter
from lending.loan_origination.decisioning import build_variable_context
from lending.loan_origination.test_decisioning import make_application, make_lead
from lending.tests.utils import LendingTestSuite

TEST_PAN = "AAAPT0000A"


SIGNED_URL = (
	"https://reports.example.com/r.pdf?X-Amz-Credential=AKIATESTKEY000000000&X-Amz-Signature=beef"
)


RESPONSE = {"reference": "bureau-ref-001", "score": "750", "document_url": SIGNED_URL}


@register
class FakeBureauAdapter(BureauAdapter):
	key = "_Test Bureau"
	bureau = "Experian"

	def parse(self, response: dict) -> dict:
		if not cint(response.get("score")):
			raise IntegrationError("the bureau refused the request")

		return {
			"external_id": response.get("reference"),
			"score": cint(response.get("score")),
			"obligations_known": False,
			"total_emi": 0,
			"report_url": response.get("document_url"),
			"payload": {k: v for k, v in response.items() if k != "document_url"},
		}


def a_pdf() -> bytes:
	"""A real, minimal PDF. Frappe reads an attachment to check it carries no JavaScript."""
	from io import BytesIO

	from pypdf import PdfWriter

	writer = PdfWriter()
	writer.add_blank_page(width=72, height=72)
	buffer = BytesIO()
	writer.write(buffer)

	return buffer.getvalue()


def use_adapter(adapter=FakeBureauAdapter.key):
	frappe.db.set_single_value("Loan Origination Settings", "credit_bureau_adapter", adapter)

	return adapter


def make_consenting_lead(**overrides):
	lead = make_lead(pan=TEST_PAN, gender="Male", bureau_consent=1, **overrides)
	lead.reload()

	return lead


class TestOnePullPerDocument(LendingTestSuite):
	def setUp(self):
		use_adapter()
		self.lead = make_consenting_lead()

	def pull(self, source):
		with patch.object(FakeBureauAdapter, "pull", return_value=RESPONSE):
			return bureau.pull_credit_bureau_report(source)

	def test_an_application_is_pulled_for_even_though_its_lead_already_was(self):
		# Underwriting decides on where the applicant stands now, not on what a lead stage
		# check found however long ago.
		lead_pull = self.pull(self.lead)
		application = make_application(loan_lead=self.lead.name)

		self.assertNotEqual(self.pull(application)["request"], lead_pull["request"])

	def test_a_pull_is_filed_against_the_document_it_was_made_for(self):
		application = make_application(loan_lead=self.lead.name)
		request = frappe.get_doc("Integration Request", self.pull(application)["request"])

		self.assertEqual(request.reference_doctype, "Loan Application")
		self.assertEqual(request.reference_docname, application.name)

	def test_one_application_is_not_enquired_about_twice(self):
		application = make_application(loan_lead=self.lead.name)

		self.assertEqual(self.pull(application)["request"], self.pull(application)["request"])

	def test_a_second_application_earns_its_own_enquiry(self):
		first = make_application(loan_lead=self.lead.name)
		second = make_application(loan_lead=self.lead.name)

		self.assertNotEqual(self.pull(first)["request"], self.pull(second)["request"])

class TestTheLeadShowsWhatWasPulled(LendingTestSuite):
	def setUp(self):
		use_adapter()
		self.lead = make_consenting_lead()

	def test_the_score_reaches_the_lead_once_the_pull_has_run(self):
		with patch.object(FakeBureauAdapter, "pull", return_value=RESPONSE):
			result = bureau.pull_credit_bureau_report(self.lead)

		# The workflow saves the lead after its tasks, which is what carries the score across.
		self.lead.save(ignore_permissions=True)
		self.lead.reload()

		self.assertEqual(self.lead.bureau_score, 750)
		self.assertEqual(self.lead.bureau_report, result["output"]["credit_bureau_report"])

	def test_a_lead_with_no_report_shows_no_score(self):
		self.lead.save(ignore_permissions=True)
		self.lead.reload()

		self.assertFalse(self.lead.bureau_score)
		self.assertFalse(self.lead.bureau_report)

class TestReportLinkIsChecked(LendingTestSuite):
	def test_a_link_into_our_own_network_is_refused(self):
		for url in ("https://127.0.0.1/r.pdf", "https://169.254.169.254/latest/meta-data/"):
			with self.assertRaises(frappe.ValidationError):
				bureau.validate_document_url(url)

	def test_a_link_that_is_not_https_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			bureau.validate_document_url("http://reports.example.com/r.pdf")

	def test_a_public_https_link_is_allowed(self):
		with self.resolving_to("93.184.216.34"):
			self.assertEqual(bureau.validate_document_url(SIGNED_URL), "93.184.216.34")

	def test_the_document_is_fetched_from_the_address_that_was_vetted(self):
		"""Looking the hostname up again would let it answer with an internal address by then."""
		session = MagicMock()
		session.get.return_value = MagicMock(is_redirect=False, **{"raw.read.return_value": a_pdf()})

		with self.resolving_to("93.184.216.34"), patch.object(
			bureau, "get_request_session", return_value=session
		):
			bureau.download_document(SIGNED_URL)

		asked = session.get.call_args
		self.assertIn("93.184.216.34", asked.args[0])
		self.assertNotIn("reports.example.com", asked.args[0])
		self.assertEqual(asked.kwargs["headers"]["Host"], "reports.example.com")

		# The certificate is still the hostname's, so a pinned address cannot be answered by anyone.
		self.assertEqual(session.mount.call_args.args[1].hostname, "reports.example.com")

	def resolving_to(self, address: str):
		return patch.object(
			bureau.socket, "getaddrinfo", return_value=[(2, 1, 6, "", (address, 443))]
		)

class TestCredentialsAndAccess(LendingTestSuite):
	def test_a_call_without_credentials_says_so_rather_than_sending_the_word_none(self):
		class Unconfigured(FakeBureauAdapter):
			key = "_Test Unconfigured"
			settings = frappe._dict(name="_Test Settings")

			def environment(self):
				return "production"

			def creds(self):
				return None, None

		with self.assertRaises(frappe.ValidationError):
			Unconfigured().auth_headers()

	def test_the_adapter_list_is_not_for_everyone_who_can_log_in(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")

		with self.assertRaises(frappe.PermissionError):
			adapter_choices()

class TestLogRedaction(LendingTestSuite):
	def test_a_link_under_a_name_we_did_not_expect_is_redacted_too(self):
		redacted = log.redact({"attachment": SIGNED_URL, "score": 750})

		self.assertEqual(redacted["attachment"], log.REDACTED)
		self.assertEqual(redacted["score"], 750)

class TestAddingAnotherBureau(LendingTestSuite):
	def test_a_new_bureau_reuses_the_whole_machinery(self):
		@register
		class EquifaxAdapter(FakeBureauAdapter):
			key = "_Test Equifax"
			bureau = "Equifax"

		self.addCleanup(registry().pop, EquifaxAdapter.key, None)

		lead = make_consenting_lead()

		with patch.object(EquifaxAdapter, "pull", return_value=RESPONSE):
			result = bureau.pull_credit_bureau_report(lead, adapter=EquifaxAdapter.key)

		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])

		self.assertEqual(report.bureau, "Equifax")
		self.assertEqual(report.score, 750)

class TestObligationsReachTheRules(LendingTestSuite):
	def make_report(self, obligations_known, total_emi=8000):
		report = frappe.get_doc(
			{
				"doctype": "Credit Bureau Report",
				"bureau": "Manual",
				"pan": TEST_PAN,
				"score": 750,
				"total_emi": total_emi,
				"obligations_known": obligations_known,
				"report_date": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		report.submit()

		return report

	def test_known_obligations_reach_the_affordability_rules(self):
		self.make_report(obligations_known=1)
		context = build_variable_context(make_lead(pan=TEST_PAN))

		self.assertEqual(context["existing_obligations"], 8000)
		self.assertIn("dti_ratio", context)

	def test_unknown_obligations_are_left_out_rather_than_read_as_zero(self):
		self.make_report(obligations_known=0, total_emi=0)
		context = build_variable_context(make_lead(pan=TEST_PAN))

		self.assertNotIn("existing_obligations", context)
		self.assertNotIn("dti_ratio", context)
