# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors

from unittest.mock import patch

import frappe
from frappe.utils import cint

from lending.loan_integrations import bureau
from lending.loan_integrations.adapters import _REGISTRY, get_adapter, register
from lending.loan_integrations.base import IntegrationError
from lending.loan_integrations.bureau import BureauAdapter
from lending.loan_origination.decisioning import build_variable_context
from lending.loan_origination.test_decisioning import make_application, make_lead
from lending.tests.utils import LendingTestSuite

# Not a PAN anybody would pull for real. Reports are filed by PAN and found by PAN, so a
# value that a live sandbox call might also use would let real data decide a test.
TEST_PAN = "AAAPT0000A"
PROVIDER = "_Test Bureau Provider"

# Bureaux hand back short lived links signed with a key that appears in the URL itself. This
# one is invented, but shaped like the real thing, because keeping it out of a log we hold
# for ten years is this app's job however the response was spelled.
SIGNED_URL = (
	"https://reports.example.com/r.pdf?X-Amz-Credential=AKIATESTKEY000000000&X-Amz-Signature=beef"
)

# Deliberately not any real provider's envelope. Lending knows what a bureau is and nothing
# about who sells one, so its tests answer in a shape no vendor uses.
RESPONSE = {"reference": "bureau-ref-001", "score": "750", "document_url": SIGNED_URL}


@register
class FakeBureauAdapter(BureauAdapter):
	"""A bureau with no vendor behind it, so the machinery can be tested without one."""

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


def make_provider(adapter=FakeBureauAdapter.key, name=PROVIDER):
	if frappe.db.exists("Loan Integration Provider", name):
		frappe.delete_doc("Loan Integration Provider", name, force=True)

	# Whatever the site has configured is not this test's business, and only one bureau may be
	# active at a time. Rolled back with the rest of the test.
	frappe.db.set_value(
		"Loan Integration Provider", {"provider_type": "Credit Bureau", "is_active": 1}, "is_active", 0
	)

	return frappe.get_doc(
		{
			"doctype": "Loan Integration Provider",
			"provider_name": name,
			"provider_type": "Credit Bureau",
			"adapter": adapter,
			"is_active": 1,
		}
	).insert(ignore_permissions=True)


def make_consenting_lead(**overrides):
	lead = make_lead(pan=TEST_PAN, gender="Male", bureau_consent=1, **overrides)
	lead.reload()

	return lead


class TestProviderRouting(LendingTestSuite):
	def test_a_provider_carries_no_credentials_of_its_own(self):
		# Credentials belong to the app that owns the vendor. A second place to put a token is
		# how somebody fills in the wrong one.
		fields = frappe.get_meta("Loan Integration Provider").get_valid_columns()

		for fieldname in ("api_secret", "sandbox_api_secret", "sandbox_url", "production_url"):
			self.assertNotIn(fieldname, fields)

	def test_a_provider_records_where_its_credentials_are(self):
		provider = make_provider()

		# This adapter needs none, so there is nothing to point at and the field says so.
		self.assertIsNone(provider.settings_doctype)
		self.assertIsInstance(get_adapter(provider.name), FakeBureauAdapter)

	def test_an_unregistered_adapter_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_provider(adapter="Nobody At All", name="_Test Missing Adapter")

	def test_two_active_bureaus_is_refused_rather_than_guessed_at(self):
		# Which bureau ran is on the applicant's credit file and on the invoice, so a second
		# active provider is a question for a human rather than something to pick between.
		make_provider()
		second = make_provider(name="_Test Second Bureau Provider")
		frappe.db.set_value("Loan Integration Provider", PROVIDER, "is_active", 1)

		with self.assertRaises(frappe.ValidationError):
			bureau.select_bureau_provider()

		self.assertTrue(second.is_active)


class TestBureauConsent(LendingTestSuite):
	def test_a_pull_without_consent_is_refused(self):
		make_provider()
		lead = make_lead(pan=TEST_PAN)

		with self.assertRaises(frappe.ValidationError):
			bureau.pull_credit_bureau_report(lead)

	def test_consent_is_stamped_when_it_is_given(self):
		lead = make_consenting_lead()

		self.assertTrue(lead.bureau_consent_on)

	def test_withdrawing_consent_clears_the_stamp(self):
		lead = make_consenting_lead()
		lead.bureau_consent = 0
		lead.save(ignore_permissions=True)

		self.assertIsNone(lead.bureau_consent_on)

	def test_an_application_consents_through_its_lead(self):
		lead = make_consenting_lead()
		application = make_application(loan_lead=lead.name)

		self.assertEqual(bureau.originating_lead(application).name, lead.name)


class TestBureauPull(LendingTestSuite):
	def setUp(self):
		self.provider = make_provider()
		self.lead = make_consenting_lead()

	def pull(self, response=None):
		with patch.object(FakeBureauAdapter, "pull", return_value=response or RESPONSE):
			return bureau.pull_credit_bureau_report(self.lead)

	def test_a_pull_files_a_submitted_report_against_the_pan(self):
		result = self.pull()
		self.assertEqual(result["status"], "Completed")

		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])

		self.assertEqual(report.docstatus, 1)
		self.assertEqual(report.bureau, "Experian")
		self.assertEqual(report.score, 750)
		self.assertEqual(report.pan, TEST_PAN)
		self.assertFalse(report.obligations_known)
		# A lead has no Customer yet, so the report is filed by PAN alone.
		self.assertFalse(report.applicant)

	def test_the_call_is_logged_against_the_lead(self):
		request = frappe.get_doc("Integration Request", self.pull()["request"])

		self.assertEqual(request.status, "Completed")
		self.assertEqual(request.reference_docname, self.lead.name)
		self.assertEqual(request.request_id, RESPONSE["reference"])

	def test_the_stored_log_carries_no_signed_link(self):
		# The link is signed with a key that appears in the URL itself. It is used during the
		# call and must not outlive it in a log we keep for ten years.
		request = frappe.get_doc("Integration Request", self.pull()["request"])

		self.assertNotIn("AKIATESTKEY000000000", request.output)
		self.assertNotIn("X-Amz-Signature", request.output)

	def test_a_second_pull_does_not_pull_again(self):
		# A hard enquiry costs money and lands on the applicant's credit file, so the same
		# document must never be pulled twice.
		first = self.pull()
		second = self.pull()

		self.assertEqual(first["request"], second["request"])
		self.assertEqual(
			frappe.db.count("Credit Bureau Report", {"external_id": ["is", "set"], "pan": TEST_PAN}), 1
		)

	def test_a_refusal_is_recorded_rather_than_raised(self):
		result = self.pull({**RESPONSE, "score": "0"})

		self.assertEqual(result["status"], "Failed")
		self.assertEqual(frappe.db.get_value("Integration Request", result["request"], "status"), "Failed")
		# The failed row survived, and nothing half written was left behind.
		self.assertFalse(frappe.db.exists("Credit Bureau Report", {"pan": TEST_PAN, "docstatus": 1}))

	def test_the_report_document_is_stored_rather_than_linked(self):
		with patch.object(bureau, "fetch_document", return_value=a_pdf()):
			result = self.pull()

		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])
		file = frappe.get_doc(
			"File", {"attached_to_doctype": report.doctype, "attached_to_name": report.name}
		)

		self.assertTrue(file.is_private)
		# The field has to survive the submit that follows the attachment.
		self.assertEqual(report.report_pdf, file.file_url)

	def test_a_report_that_cannot_be_attached_does_not_lose_the_score(self):
		# Frappe refuses a PDF it cannot read. The pull was still billed and the enquiry still
		# landed on the applicant's file, so the score has to survive the attachment failing.
		with patch.object(bureau, "fetch_document", return_value=b"not really a pdf"):
			result = self.pull()

		self.assertEqual(result["status"], "Completed")
		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])

		self.assertEqual(report.score, 750)
		self.assertFalse(report.report_pdf)


class TestAddingAnotherBureau(LendingTestSuite):
	"""A second bureau should be a class, not a project — whoever it is bought from."""

	def test_a_new_bureau_reuses_the_whole_machinery(self):
		@register
		class EquifaxAdapter(FakeBureauAdapter):
			key = "_Test Equifax"
			bureau = "Equifax"

		self.addCleanup(_REGISTRY.pop, EquifaxAdapter.key, None)

		provider = make_provider(adapter=EquifaxAdapter.key, name="_Test Equifax Provider")
		lead = make_consenting_lead()

		with patch.object(EquifaxAdapter, "pull", return_value=RESPONSE):
			result = bureau.pull_credit_bureau_report(lead, provider=provider.name)

		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])

		# Same logging, same report, same rules — only the bureau changed.
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
		# Left out, the rule that needs it is skipped and an approval is downgraded to a
		# referral. Read as zero, every affordability rule would pass on a number nobody gave.
		self.make_report(obligations_known=0, total_emi=0)
		context = build_variable_context(make_lead(pan=TEST_PAN))

		self.assertNotIn("existing_obligations", context)
		self.assertNotIn("dti_ratio", context)
