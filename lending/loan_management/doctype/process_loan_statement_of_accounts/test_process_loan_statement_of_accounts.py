# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

from lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts import (
	get_applicant_details,
	get_report_filters,
	get_statement_dict,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	make_loan_disbursement_entry,
)
from lending.tests.utils import LendingTestSuite


class TestProcessLoanStatementofAccounts(LendingTestSuite):
	def create_process_doc(self, applicant, **kwargs):
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
				"applicants": [
					{
						"applicant_type": "Customer",
						"applicant": applicant,
						"applicant_name": applicant,
						"email": "test@example.com",
					}
				],
			}
		)
		doc.update(kwargs)
		doc.insert()
		return doc

	def make_loan_with_activity(self):
		loan = create_loan(
			"_Test Loan Customer",
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

	def test_get_report_filters_maps_doc_to_report(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer", loan_product="Term Loan Product 4")

		filters = get_report_filters(doc, doc.applicants[0])
		self.assertEqual(filters["company"], "_Test Company")
		self.assertEqual(filters["applicant_type"], "Customer")
		self.assertEqual(filters["applicant"], "_Test Loan Customer")
		self.assertEqual(filters["loan_product"], "Term Loan Product 4")
		self.assertEqual(filters["group_by"], "Detailed")

	def test_statement_dict_renders_html_for_applicant(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer")

		statement_dict = get_statement_dict(doc)

		self.assertIn("_Test Loan Customer", statement_dict)
		html = statement_dict["_Test Loan Customer"]
		self.assertIn("LOAN STATEMENT OF ACCOUNT", html)
		# Disbursement debit (120000) should appear in the rendered statement,
		# formatted per the company's number format (grouping may vary).
		from frappe.utils import fmt_money

		default_currency = frappe.get_cached_value("Company", "_Test Company", "default_currency")
		self.assertIn(fmt_money(120000, currency=default_currency), html)

	def test_get_applicant_details_returns_name(self):
		details = get_applicant_details("Customer", "_Test Loan Customer")
		self.assertIn("applicant_name", details)
		self.assertIn("email", details)

	def test_statement_dict_uses_selected_currency(self):
		self.make_loan_with_activity()
		doc = self.create_process_doc("_Test Loan Customer", currency="USD")

		statement_dict = get_statement_dict(doc)
		html = statement_dict["_Test Loan Customer"]
		self.assertIn("$", html)

	def test_statement_dict_skips_applicant_without_data(self):
		# Customer with no loans in the date window must be skipped
		doc = self.create_process_doc("_Test Loan Customer 2")
		doc.from_date = "1990-01-01"
		doc.to_date = "1990-12-31"

		statement_dict = get_statement_dict(doc)
		self.assertNotIn("_Test Loan Customer 2", statement_dict)
