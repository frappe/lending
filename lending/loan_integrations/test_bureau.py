# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors

from unittest.mock import patch

import frappe
from frappe.utils import add_days, cint

from lending.loan_integrations import bureau, log
from lending.loan_integrations.adapters import get_adapter, register
from lending.loan_integrations.base import IntegrationError
from lending.loan_integrations.bureau import BureauAdapter
from lending.loan_origination.test_decisioning import make_application, make_lead
from lending.tests.utils import LendingTestSuite

TEST_PAN = "AAAPT0000A"


SIGNED_URL = (
	"https://reports.example.com/r.pdf?X-Amz-Credential=AKIATESTKEY000000000&X-Amz-Signature=beef"
)


RESPONSE = {"reference": "bureau-ref-001", "score": "750", "document_url": SIGNED_URL}


@register
class StubBureauAdapter(BureauAdapter):
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


def use_adapter(adapter=StubBureauAdapter.key):
	frappe.db.set_single_value("Loan Origination Settings", "credit_bureau_adapter", adapter)

	return adapter


def make_consenting_lead(**overrides):
	lead = make_lead(pan=TEST_PAN, gender="Male", bureau_consent=1, **overrides)
	lead.reload()

	return lead


class TestAdapterRouting(LendingTestSuite):
	def test_the_settings_pick_the_adapter(self):
		use_adapter()

		self.assertEqual(bureau.select_bureau_adapter(), StubBureauAdapter.key)
		self.assertIsInstance(get_adapter(StubBureauAdapter.key), StubBureauAdapter)

	def test_an_unregistered_adapter_is_refused(self):
		settings = frappe.get_doc("Loan Origination Settings")
		settings.credit_bureau_adapter = "Nobody At All"

		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_a_pull_with_no_adapter_set_is_refused(self):
		use_adapter("")

		with self.assertRaises(frappe.ValidationError):
			bureau.select_bureau_adapter()

class TestBureauConsent(LendingTestSuite):
	def test_a_pull_without_consent_is_refused(self):
		use_adapter()
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

	def test_a_consent_date_sent_by_a_client_is_not_believed(self):
		lead = make_consenting_lead()
		stamped = lead.bureau_consent_on

		lead.bureau_consent_on = add_days(stamped, -30)
		lead.bureau_consent_version = "forged"
		lead.save(ignore_permissions=True)
		lead.reload()

		self.assertEqual(lead.bureau_consent_on, stamped)
		self.assertNotEqual(lead.bureau_consent_version, "forged")

	def test_a_new_lead_cannot_arrive_carrying_its_own_consent_date(self):
		lead = make_lead(pan=TEST_PAN, bureau_consent=1, bureau_consent_on="2020-01-01 00:00:00")
		lead.reload()

		self.assertNotEqual(str(lead.bureau_consent_on), "2020-01-01 00:00:00")

class TestBureauPull(LendingTestSuite):
	def setUp(self):
		use_adapter()
		self.lead = make_consenting_lead()

	def pull(self, response=None):
		with patch.object(StubBureauAdapter, "pull", return_value=response or RESPONSE):
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
		self.assertFalse(report.applicant)

	def test_the_call_is_logged_against_the_lead(self):
		request = frappe.get_doc("Integration Request", self.pull()["request"])

		self.assertEqual(request.status, "Completed")
		self.assertEqual(request.reference_docname, self.lead.name)
		self.assertEqual(request.request_id, RESPONSE["reference"])

	def test_the_stored_log_carries_no_signed_link(self):
		request = frappe.get_doc("Integration Request", self.pull()["request"])

		self.assertNotIn("AKIATESTKEY000000000", request.output)
		self.assertNotIn("X-Amz-Signature", request.output)

	def test_the_stored_log_carries_no_applicant_identifiers(self):
		request = frappe.get_doc("Integration Request", self.pull()["request"])

		self.assertEqual(request.reference_docname, self.lead.name)
		self.assertNotIn(TEST_PAN, request.data)

	def test_a_failed_fetch_keeps_the_signed_link_out_of_the_error_log(self):
		with patch.object(
			bureau, "download_document", side_effect=ConnectionError("the link expired")
		):
			self.assertIsNone(bureau.fetch_document(SIGNED_URL))

		logged = frappe.get_all(
			"Error Log",
			filters={"method": "Could not fetch the bureau report document"},
			fields=["error"],
			order_by="creation desc",
			limit=1,
		)

		self.assertTrue(logged)
		self.assertNotIn("AKIATESTKEY000000000", logged[0].error)
		self.assertNotIn("X-Amz-Signature", logged[0].error)
		self.assertIn("reports.example.com", logged[0].error)

	def test_a_second_pull_does_not_pull_again(self):
		first = self.pull()
		second = self.pull()

		self.assertEqual(first["request"], second["request"])
		self.assertEqual(
			frappe.db.count("Credit Bureau Report", {"external_id": ["is", "set"], "pan": TEST_PAN}), 1
		)
		self.assertEqual(second["status"], "Completed")
		self.assertEqual(
			second["output"]["credit_bureau_report"], first["output"]["credit_bureau_report"]
		)

	def test_a_call_left_open_is_settled_by_a_person_rather_than_repeated(self):
		result = self.pull()
		frappe.db.set_value("Integration Request", result["request"], "status", "Queued")

		with self.assertRaises(frappe.ValidationError):
			self.pull()

	def test_a_refusal_is_recorded_rather_than_raised(self):
		result = self.pull({**RESPONSE, "score": "0"})

		self.assertEqual(result["status"], log.UNRECORDED)
		self.assertEqual(
			frappe.db.get_value("Integration Request", result["request"], "status"), log.UNRECORDED
		)
		self.assertFalse(frappe.db.exists("Credit Bureau Report", {"pan": TEST_PAN, "docstatus": 1}))

	def test_an_answer_we_could_not_store_is_not_paid_for_twice(self):
		# The bureau answered, so the enquiry is on the applicant's file whatever we made of it.
		spent = self.pull({**RESPONSE, "score": "0"})

		with self.assertRaises(frappe.ValidationError):
			self.pull()

		self.assertEqual(frappe.db.count("Integration Request", {"reference_docname": self.lead.name}), 1)
		self.assertEqual(
			frappe.db.get_value("Integration Request", spent["request"], "status"), log.UNRECORDED
		)

	def test_an_answer_we_could_not_store_keeps_the_bureau_reference(self):
		with patch.object(StubBureauAdapter, "persist", side_effect=IntegrationError("no room")):
			result = self.pull()

		self.assertEqual(result["status"], log.UNRECORDED)
		self.assertEqual(
			frappe.db.get_value("Integration Request", result["request"], "request_id"),
			RESPONSE["reference"],
		)

	def test_a_bureau_that_never_answered_is_asked_again(self):
		with patch.object(StubBureauAdapter, "pull", side_effect=ConnectionError("no route")):
			unreachable = bureau.pull_credit_bureau_report(self.lead)

		self.assertEqual(unreachable["status"], log.FAILED)

		retried = self.pull()

		self.assertEqual(retried["status"], "Completed")
		self.assertNotEqual(retried["request"], unreachable["request"])

	def test_the_report_document_is_stored_rather_than_linked(self):
		with patch.object(bureau, "fetch_document", return_value=a_pdf()):
			result = self.pull()

		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])
		file = frappe.get_doc(
			"File", {"attached_to_doctype": report.doctype, "attached_to_name": report.name}
		)

		self.assertTrue(file.is_private)
		self.assertEqual(report.report_pdf, file.file_url)

	def test_a_report_that_cannot_be_attached_does_not_lose_the_score(self):
		with patch.object(bureau, "fetch_document", return_value=b"not really a pdf"):
			result = self.pull()

		self.assertEqual(result["status"], "Completed")
		report = frappe.get_doc("Credit Bureau Report", result["output"]["credit_bureau_report"])

		self.assertEqual(report.score, 750)
		self.assertFalse(report.report_pdf)
