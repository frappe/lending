# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import patch

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
				"from_date": "2000-01-01",
				"to_date": "2099-12-31",
				"group_by": "Detailed",
				"applicants": applicants,
			}
		)
		doc.update(kwargs)
		doc.insert()
		return doc

	def make_loan_with_activity(self, applicant="_Test Loan Customer"):
		loan = create_loan(
			applicant,
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			repayment_start_date="2024-02-05",
			posting_date="2024-01-05",
			rate_of_interest=10,
		)
		loan.submit()

		disb = make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-01-05",
			repayment_start_date="2024-02-05",
		)
		repayment = create_repayment_entry(loan.name, "2024-02-05", 10000, loan_disbursement=disb.name)
		repayment.submit()
		return loan

	# ---------- validate ----------

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
				"from_date": "2000-01-01",
				"to_date": "2099-12-31",
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

	# ---------- helpers ----------

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
		# applicants child rows are stripped from the template doc
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

	# ---------- statement / pdf ----------

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

	def test_statement_dict_uses_selected_currency(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer", currency="USD")

		statement_dict = get_statement_dict(doc)
		html = statement_dict["_Test Loan Customer"]
		self.assertIn("$", html)

	def test_statement_dict_skips_applicant_without_data(self):
		doc = self.create_process_doc("_Test Loan Customer 2")
		doc.from_date = "1990-01-01"
		doc.to_date = "1990-12-31"

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
		doc.from_date = "1990-01-01"
		doc.to_date = "1990-12-31"
		self.assertFalse(get_report_pdf(doc))

	def test_download_statements_sets_response(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")
		download_statements(doc.name)
		self.assertEqual(frappe.local.response.type, "download")
		self.assertEqual(frappe.local.response.filename, doc.name + ".pdf")

	# ---------- fetch_applicants ----------

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

	# ---------- send_emails / scheduler ----------

	def test_send_emails_enqueues_and_returns_true(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")
		with patch(
			"lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts.frappe.enqueue"
		) as mock_enqueue:
			result = send_emails(doc.name)
		self.assertTrue(result)
		self.assertTrue(mock_enqueue.called)

	def test_send_emails_returns_false_without_data(self):
		doc = self.create_process_doc("_Test Loan Customer 2")
		doc.from_date = "1990-01-01"
		doc.to_date = "1990-12-31"
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
		with patch(
			"lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts.frappe.enqueue"
		) as mock_enqueue:
			result = send_emails(doc.name)
		self.assertTrue(result)
		self.assertFalse(mock_enqueue.called)

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
		with patch(
			"lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts.frappe.enqueue"
		):
			send_auto_email()
		# start_date should have been rolled forward past today
		self.assertGreater(
			getdate(frappe.db.get_value(doc.doctype, doc.name, "start_date")), getdate(today())
		)
