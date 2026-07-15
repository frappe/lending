# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, add_months, getdate, today

from lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts import (
	download_statements,
	fetch_applicants,
	get_applicant_details,
	get_applicant_email,
	get_context,
	get_recipients_and_cc,
	get_report_filters,
	get_report_pdf,
	get_statement_dict,
	send_auto_email,
	send_emails,
	set_next_schedule_date,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	make_loan_disbursement_entry,
)
from lending.tests.utils import LendingTestSuite


class TestProcessLoanStatementofAccounts(LendingTestSuite):
	def create_process_doc(self, applicant, **kwargs):
		applicants = kwargs.pop("applicants", None) or [
			{
				"applicant_type": "Customer",
				"applicant": applicant,
				"applicant_name": applicant,
				"email": "test@example.com",
			}
		]
		doc = frappe.get_doc(
			{
				"doctype": "Process Loan Statement of Accounts",
				"__newname": frappe.generate_hash(length=10),
				"report": "Loan Statement of Account",
				"company": "_Test Company",
				"applicant_type": "Customer",
				"from_date": add_months(today(), -12),
				"to_date": today(),
				"group_by": "Detailed",
				"applicants": applicants,
			}
		)
		doc.update(kwargs)
		doc.insert()
		return doc

	def make_loan_with_activity(self, applicant="_Test Loan Customer"):
		posting_date = add_months(today(), -2)
		repayment_date = add_months(today(), -1)
		loan = create_loan(
			applicant,
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			repayment_start_date=repayment_date,
			posting_date=posting_date,
			rate_of_interest=10,
		)
		loan.submit()

		disb = make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			repayment_start_date=repayment_date,
		)
		repayment = create_repayment_entry(loan.name, repayment_date, 10000, loan_disbursement=disb.name)
		repayment.submit()
		return loan

	def test_validate_sets_default_email_templates(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")

		self.assertIn("{{ applicant.applicant_name }}", doc.subject)
		self.assertIn("{{ applicant.applicant_name }}", doc.body)
		self.assertEqual(doc.pdf_name, "{{ applicant.applicant_name }}")

	def test_validate_throws_without_applicants(self):
		doc = frappe.get_doc(
			{
				"doctype": "Process Loan Statement of Accounts",
				"__newname": frappe.generate_hash(length=10),
				"report": "Loan Statement of Account",
				"company": "_Test Company",
				"applicant_type": "Customer",
				"from_date": add_months(today(), -12),
				"to_date": today(),
				"applicants": [],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_validate_syncs_dates_when_auto_email_enabled(self):
		self.make_loan_with_activity()
		start = add_days(today(), 5)
		doc = self.create_process_doc(
			"_Test Loan Customer",
			enable_auto_email=1,
			start_date=start,
			filter_duration=6,
		)
		self.assertEqual(getdate(doc.to_date), getdate(start))
		self.assertEqual(getdate(doc.from_date), add_months(getdate(start), -6))

	def test_get_report_filters_maps_doc_to_report(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer", loan_product="Term Loan Product 4")

		filters = get_report_filters(doc, doc.applicants[0])
		self.assertEqual(filters["company"], "_Test Company")
		self.assertEqual(filters["applicant_type"], "Customer")
		self.assertEqual(filters["applicant"], "_Test Loan Customer")
		self.assertEqual(filters["loan_product"], "Term Loan Product 4")
		self.assertEqual(filters["group_by"], "Detailed")

	def test_get_applicant_email_customer(self):
		frappe.db.set_value("Customer", "_Test Loan Customer", "email_id", "cust@example.com")
		self.assertEqual(get_applicant_email("Customer", "_Test Loan Customer"), "cust@example.com")
		self.assertEqual(get_applicant_email("Supplier", "_Test Loan Customer"), "")

	def test_get_applicant_details_returns_name_and_email(self):
		frappe.db.set_value("Customer", "_Test Loan Customer", "email_id", "cust@example.com")
		details = get_applicant_details("Customer", "_Test Loan Customer")
		self.assertIn("applicant_name", details)
		self.assertEqual(details["email"], "cust@example.com")

	def test_get_context_strips_applicants_and_formats_dates(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")
		context = get_context(doc.applicants[0], doc)
		self.assertFalse(context["doc"].get("applicants"))
		self.assertEqual(context["applicant"].applicant, "_Test Loan Customer")

	def test_get_recipients_and_cc(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc(
			"_Test Loan Customer",
			applicants=[
				{
					"applicant_type": "Customer",
					"applicant": "_Test Loan Customer",
					"applicant_name": "_Test Loan Customer",
					"email": "a@example.com, b@example.com",
				}
			],
		)
		recipients, cc = get_recipients_and_cc(doc.applicants[0], doc)
		self.assertEqual(recipients, ["a@example.com", "b@example.com"])
		self.assertEqual(cc, [])

	def test_statement_dict_renders_html_for_applicant(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")

		statement_dict = get_statement_dict(doc)

		self.assertIn("_Test Loan Customer", statement_dict)
		html = statement_dict["_Test Loan Customer"]
		self.assertIn("LOAN STATEMENT OF ACCOUNT", html)
		from frappe.utils import fmt_money

		default_currency = frappe.get_cached_value("Company", "_Test Company", "default_currency")
		self.assertIn(fmt_money(120000, currency=default_currency), html)

	def test_letter_head_jinja_is_rendered(self):
		from lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts import (
			get_rendered_letter_head,
		)

		if not frappe.db.exists("Letter Head", "Company Letterhead"):
			self.skipTest("Company Letterhead not available")

		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer", letter_head="Company Letterhead")

		letter_head = get_rendered_letter_head(doc, applicant="_Test Loan Customer")
		rendered = letter_head["content"]

		self.assertNotIn("{{", rendered)
		self.assertNotIn("Process Loan Statement of Accounts", rendered)
		self.assertIn("Loan Statement of Account", rendered)
		self.assertIn("_Test Loan Customer", rendered)

	def test_statement_dict_skips_applicant_without_data(self):
		doc = self.create_process_doc("_Test Loan Customer 2")
		doc.from_date = add_months(today(), 1)
		doc.to_date = add_months(today(), 12)

		statement_dict = get_statement_dict(doc)
		self.assertNotIn("_Test Loan Customer 2", statement_dict)

	def test_get_report_pdf_consolidated(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")
		pdf = get_report_pdf(doc, consolidated=True)
		self.assertTrue(pdf)
		self.assertIsInstance(pdf, bytes)

	def test_get_report_pdf_per_applicant(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")
		report = get_report_pdf(doc, consolidated=False)
		self.assertIn("_Test Loan Customer", report)
		self.assertIsInstance(report["_Test Loan Customer"], bytes)

	def test_get_report_pdf_returns_false_without_data(self):
		doc = self.create_process_doc("_Test Loan Customer 2")
		doc.from_date = add_months(today(), 1)
		doc.to_date = add_months(today(), 12)
		self.assertFalse(get_report_pdf(doc))

	def test_download_statements_sets_response(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")
		download_statements(doc.name)
		self.assertEqual(frappe.local.response.type, "download")
		self.assertEqual(frappe.local.response.filename, doc.name + ".pdf")

	def test_fetch_applicants_all_loans(self):
		self.make_loan_with_activity()
		result = fetch_applicants("_Test Company", "Customer", "All Loans")
		applicants = [r["applicant"] for r in result]
		self.assertIn("_Test Loan Customer", applicants)

	def test_fetch_applicants_by_loan_product(self):
		self.make_loan_with_activity()
		result = fetch_applicants("_Test Company", "Customer", "Loan Product", "Term Loan Product 4")
		self.assertTrue(result)
		self.assertTrue(all("applicant" in r for r in result))

	def test_fetch_applicants_loan_product_required(self):
		with self.assertRaises(frappe.ValidationError):
			fetch_applicants("_Test Company", "Customer", "Loan Product")

	def test_send_emails_returns_true_and_queues_mail(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")

		result = send_emails(doc.name)

		self.assertTrue(result)
		queued = frappe.db.count(
			"Email Queue",
			filters={
				"reference_doctype": "Process Loan Statement of Accounts",
				"reference_name": doc.name,
			},
		)
		self.assertGreater(queued, 0)

	def test_send_emails_returns_false_without_data(self):
		doc = self.create_process_doc("_Test Loan Customer 2")
		doc.from_date = add_months(today(), 1)
		doc.to_date = add_months(today(), 12)
		doc.save()
		self.assertFalse(send_emails(doc.name))

	def test_send_emails_skips_applicant_without_recipients(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc(
			"_Test Loan Customer",
			applicants=[
				{
					"applicant_type": "Customer",
					"applicant": "_Test Loan Customer",
					"applicant_name": "_Test Loan Customer",
					"email": "",
				}
			],
		)
		result = send_emails(doc.name)

		self.assertTrue(result)
		queued = frappe.db.count(
			"Email Queue",
			filters={
				"reference_doctype": "Process Loan Statement of Accounts",
				"reference_name": doc.name,
			},
		)
		self.assertEqual(queued, 0)

	def test_set_next_schedule_date_monthly(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer", frequency="Monthly", filter_duration=6)
		set_next_schedule_date(doc)
		expected_to = add_months(getdate(today()), 1)
		self.assertEqual(getdate(frappe.db.get_value(doc.doctype, doc.name, "to_date")), expected_to)
		self.assertEqual(
			getdate(frappe.db.get_value(doc.doctype, doc.name, "from_date")),
			add_months(expected_to, -6),
		)

	def test_set_next_schedule_date_weekly(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer", frequency="Weekly", filter_duration=12)
		set_next_schedule_date(doc)
		expected_to = add_days(getdate(today()), 7)
		self.assertEqual(getdate(frappe.db.get_value(doc.doctype, doc.name, "to_date")), expected_to)

	def test_set_next_schedule_date_quarterly(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer", frequency="Quarterly", filter_duration=12)
		set_next_schedule_date(doc)
		expected_to = add_months(getdate(today()), 3)
		self.assertEqual(getdate(frappe.db.get_value(doc.doctype, doc.name, "to_date")), expected_to)

	def test_send_auto_email_processes_due_docs(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc(
			"_Test Loan Customer",
			enable_auto_email=1,
			start_date=today(),
			frequency="Monthly",
			filter_duration=6,
		)
		send_auto_email()

		self.assertGreater(
			getdate(frappe.db.get_value(doc.doctype, doc.name, "start_date")), getdate(today())
		)

	def test_send_auto_email_processes_overdue_docs(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc(
			"_Test Loan Customer",
			enable_auto_email=1,
			frequency="Monthly",
			filter_duration=6,
		)
		frappe.db.set_value(doc.doctype, doc.name, "start_date", add_days(today(), -3))

		send_auto_email()

		self.assertGreater(
			getdate(frappe.db.get_value(doc.doctype, doc.name, "start_date")), getdate(today())
		)
