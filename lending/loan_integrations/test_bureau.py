# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors

from unittest.mock import patch

import frappe

from lending.loan_integrations import bureau
from lending.loan_integrations.adapters import _REGISTRY, get_adapter, register
from lending.loan_integrations.adapters.surepass import SurepassBureauAdapter
from lending.loan_integrations.base import IntegrationError
from lending.loan_origination.decisioning import build_variable_context
from lending.loan_origination.test_decisioning import make_application, make_lead
from lending.tests.utils import LendingTestSuite

TEST_PAN = "EKRPR1234F"
PROVIDER = "_Test Surepass"

# The response Surepass's sandbox actually returns, kept whole so a change in their envelope
# fails here rather than in production.
SANDBOX_RESPONSE = {
	"data": {
		"client_id": "credit_report_cibil_pdf_xfOSfdDRgierjgNdZelb",
		"name": "VISHAL RATHORE",
		"mobile": "9988776655",
		"pan": TEST_PAN,
		"gender": "male",
		"user_email": None,
		"credit_score": "750",
		"credit_report": None,
		"credit_report_link": (
			"https://aadhaar-kyc-docs.s3.amazonaws.com/user123/credit_report_cibil/report.pdf"
			"?X-Amz-Credential=AKIAY5K3QRM5KVPBYKKE%2F20260806%2Fap-south-1%2Fs3%2Faws4_request"
			"&X-Amz-Expires=600&X-Amz-Signature=c5168167bdab60bf30e2b27ac148585a4b474633"
		),
		"credit_report_base64": None,
	},
	"status_code": 200,
	"success": True,
	"message": "Success",
	"message_code": "success",
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


def make_provider(adapter="Surepass CIBIL", name=PROVIDER):
	if frappe.db.exists("Loan Integration Provider", name):
		frappe.delete_doc("Loan Integration Provider", name, force=True)

	return frappe.get_doc(
		{
			"doctype": "Loan Integration Provider",
			"provider_name": name,
			"provider_type": "Credit Bureau",
			"adapter": adapter,
			"is_active": 1,
			"enable_sandbox": 1,
			"sandbox_url": "https://sandboxapp.surepass.app/sandbox/api/v1",
			"sandbox_api_secret": "a-test-token",
		}
	).insert(ignore_permissions=True)


def make_consenting_lead(**overrides):
	lead = make_lead(pan=TEST_PAN, gender="Male", bureau_consent=1, **overrides)
	lead.reload()

	return lead


class TestSurepassParsing(LendingTestSuite):
	def setUp(self):
		self.adapter = get_adapter(make_provider().name)

	def test_it_reads_the_score_out_of_the_envelope(self):
		parsed = self.adapter.parse(SANDBOX_RESPONSE)

		self.assertEqual(parsed["score"], 750)
		self.assertEqual(parsed["external_id"], "credit_report_cibil_pdf_xfOSfdDRgierjgNdZelb")

	def test_it_does_not_claim_to_know_the_obligations(self):
		# The endpoint returns no obligations, and saying so is what keeps the affordability
		# rules from reading an unfilled field as an applicant who owes nothing.
		self.assertFalse(self.adapter.parse(SANDBOX_RESPONSE)["obligations_known"])

	def test_it_keeps_the_signed_link_out_of_the_stored_payload(self):
		parsed = self.adapter.parse(SANDBOX_RESPONSE)

		self.assertNotIn("credit_report_link", parsed["payload"])
		self.assertNotIn("AKIAY5K3QRM5KVPBYKKE", frappe.as_json(parsed["payload"]))
		# Dropped from what we store, but still used to fetch the document during the call.
		self.assertIn("X-Amz-Signature", parsed["report_url"])

	def test_a_score_below_the_floor_is_not_a_score(self):
		response = {**SANDBOX_RESPONSE, "data": {**SANDBOX_RESPONSE["data"], "credit_score": "-1"}}

		self.assertEqual(self.adapter.parse(response)["score"], 0)

	def test_a_failure_reported_in_the_body_is_a_failure(self):
		# Surepass answers HTTP 200 and says so in the body, so raise_for_status sees nothing.
		response = {**SANDBOX_RESPONSE, "success": False, "message": "PAN not found"}

		with self.assertRaises(IntegrationError):
			self.adapter.parse(response)

	def test_it_authenticates_with_a_bearer_token(self):
		self.assertEqual(self.adapter.auth_headers()["Authorization"], "Bearer a-test-token")


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
		with patch.object(SurepassBureauAdapter, "pull", return_value=response or SANDBOX_RESPONSE):
			return bureau.pull_credit_bureau_report(self.lead)

	def test_a_pull_files_a_submitted_report_against_the_pan(self):
		result = self.pull()
		self.assertEqual(result["status"], "Completed")

		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])

		self.assertEqual(report.docstatus, 1)
		self.assertEqual(report.bureau, "CIBIL")
		self.assertEqual(report.score, 750)
		self.assertEqual(report.pan, TEST_PAN)
		self.assertFalse(report.obligations_known)
		# A lead has no Customer yet, so the report is filed by PAN alone.
		self.assertFalse(report.applicant)

	def test_the_call_is_logged_against_the_lead(self):
		request = frappe.get_doc("Integration Request", self.pull()["request"])

		self.assertEqual(request.status, "Completed")
		self.assertEqual(request.reference_docname, self.lead.name)
		self.assertEqual(request.request_id, SANDBOX_RESPONSE["data"]["client_id"])

	def test_the_stored_log_carries_no_signed_link(self):
		# The link Surepass returns is signed with an AWS key that appears in the URL itself.
		# It is used during the call and must not outlive it in a log we keep for ten years.
		request = frappe.get_doc("Integration Request", self.pull()["request"])

		self.assertNotIn("AKIAY5K3QRM5KVPBYKKE", request.output)
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
		result = self.pull({**SANDBOX_RESPONSE, "success": False, "message": "PAN not found"})

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
	"""Adding the next bureau Surepass carries should be a class, not a project."""

	def test_a_new_bureau_is_an_endpoint_and_a_name(self):
		@register
		class SurepassCrifAdapter(SurepassBureauAdapter):
			key = "_Test Surepass CRIF"
			bureau = "CRIF"
			endpoint = "/credit-report-crif/fetch-report-pdf"

		self.addCleanup(_REGISTRY.pop, SurepassCrifAdapter.key, None)

		provider = make_provider(adapter=SurepassCrifAdapter.key, name="_Test Surepass CRIF Provider")
		lead = make_consenting_lead()

		with patch.object(SurepassBureauAdapter, "pull", return_value=SANDBOX_RESPONSE):
			result = bureau.pull_credit_bureau_report(lead, provider=provider.name)

		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])

		# Same envelope, same logging, same report — only the bureau changed.
		self.assertEqual(report.bureau, "CRIF")
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
