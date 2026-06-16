# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import copy

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, format_date, getdate, today
from frappe.utils.jinja import validate_template
from frappe.utils.pdf import get_pdf
from frappe.www.printview import get_print_style

from lending.loan_management.report.loan_statement_of_account.loan_statement_of_account import (
	execute as get_loan_soa,
)

REPORT_NAME = "Loan Statement of Account"
TEMPLATE_PATH = "lending/loan_management/doctype/process_loan_statement_of_accounts/process_loan_statement_of_accounts.html"


class ProcessLoanStatementofAccounts(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.accounts.doctype.process_statement_of_accounts_cc.process_statement_of_accounts_cc import (
			ProcessStatementOfAccountsCC,
		)

		from lending.loan_management.doctype.process_loan_statement_of_accounts_applicant.process_loan_statement_of_accounts_applicant import (
			ProcessLoanStatementofAccountsApplicant,
		)

		applicant_type: DF.Literal["Customer", "Employee"]
		applicants: DF.Table[ProcessLoanStatementofAccountsApplicant]
		body: DF.TextEditor | None
		cc_to: DF.TableMultiSelect[ProcessStatementOfAccountsCC]
		collection_based_on: DF.Literal["", "Loan Product", "All Loans"]
		company: DF.Link
		enable_auto_email: DF.Check
		filter_duration: DF.Int
		frequency: DF.Literal["Daily", "Weekly", "Biweekly", "Monthly", "Quarterly"]
		from_date: DF.Date | None
		group_by: DF.Literal["Detailed", "Grouped"]
		include_break: DF.Check
		letter_head: DF.Link | None
		loan_product: DF.Link | None
		orientation: DF.Literal["Portrait", "Landscape"]
		pdf_name: DF.Data | None
		report: DF.Literal["Loan Statement of Account"]
		sender: DF.Link | None
		start_date: DF.Date | None
		subject: DF.Data | None
		terms_and_conditions: DF.Link | None
		to_date: DF.Date | None
	# end: auto-generated types

	def validate(self):
		if not self.subject:
			self.subject = "Loan Statement Of Account for {{ applicant.applicant_name }}"
		if not self.body:
			self.body = (
				"Hello {{ applicant.applicant_name }},<br>"
				"PFA your Loan Statement Of Account from {{ doc.from_date }} to {{ doc.to_date }}."
			)
		if not self.pdf_name:
			self.pdf_name = "{{ applicant.applicant_name }}"

		validate_template(self.subject)
		validate_template(self.body)
		validate_template(self.pdf_name)

		if not self.applicants:
			frappe.throw(_("Applicants not selected."))

		# Keep the date window in sync for the next scheduled run.
		if self.enable_auto_email and self.start_date and getdate(self.start_date) >= getdate(today()):
			self.to_date = self.start_date
			self.from_date = add_months(self.to_date, -1 * (self.filter_duration or 12))


def get_report_filters(doc, entry):
	return frappe._dict(
		{
			"company": doc.company,
			"applicant_type": entry.applicant_type,
			"applicant": entry.applicant,
			"loan_product": doc.loan_product or None,
			"from_date": doc.from_date,
			"to_date": doc.to_date,
			"group_by": doc.group_by or "Detailed",
		}
	)


def get_statement_dict(doc):
	"""Return {applicant_name_in_table: rendered_html} for each applicant with data."""
	statement_dict = {}
	presentation_currency = doc.currency or frappe.get_cached_value(
		"Company", doc.company, "default_currency"
	)

	for entry in doc.applicants:
		filters = get_report_filters(doc, entry)
		columns, data = get_loan_soa(filters)
		if not data:
			continue
		# Display-only currency code; the report keeps values in company currency.
		for row in data:
			row["currency"] = presentation_currency
		statement_dict[entry.applicant] = get_html(doc, filters, columns, data)

	return statement_dict


def get_html(doc, filters, columns, data):
	base_template_path = "frappe/www/printview.html"

	letter_head = None
	if doc.letter_head:
		from frappe.www.printview import get_letter_head

		letter_head = get_letter_head(doc, 0)

	# The Loan Statement of Account report uses a client-side (frappe.render) HTML
	# template. Render it server-side via the jinja-compatible report renderer.
	html = frappe.render_template(
		TEMPLATE_PATH,
		{
			"filters": filters,
			"data": data,
			"report": {"report_name": REPORT_NAME, "columns": columns},
			"letter_head": letter_head,
			"terms_and_conditions": frappe.db.get_value(
				"Terms and Conditions", doc.terms_and_conditions, "terms"
			)
			if doc.terms_and_conditions
			else None,
		},
	)

	html = frappe.render_template(
		base_template_path,
		{
			"body": html,
			"css": get_print_style(),
			"title": "Loan Statement For " + filters.applicant,
		},
	)
	return html


def get_report_pdf(doc, consolidated=True):
	statement_dict = get_statement_dict(doc)
	if not statement_dict:
		return False
	elif consolidated:
		delimiter = '<div style="page-break-before: always;"></div>' if doc.include_break else ""
		result = delimiter.join(list(statement_dict.values()))
		return get_pdf(result, {"orientation": doc.orientation})
	else:
		for applicant, statement_html in statement_dict.items():
			statement_dict[applicant] = get_pdf(statement_html, {"orientation": doc.orientation})
		return statement_dict


def get_context(entry, doc):
	template_doc = copy.deepcopy(doc)
	del template_doc.applicants
	template_doc.from_date = format_date(template_doc.from_date)
	template_doc.to_date = format_date(template_doc.to_date)
	return {
		"doc": template_doc,
		"applicant": entry,
		"frappe": frappe.utils,
	}


def get_recipients_and_cc(entry, doc):
	recipients = []
	if entry.email:
		for email in entry.email.split(","):
			email = email.strip()
			if email:
				recipients.append(email)

	cc = []
	for user in doc.cc_to or []:
		email = frappe.get_value("User", user.cc, "email")
		if email:
			cc.append(email)

	return recipients, cc


def get_applicant_email(applicant_type, applicant):
	if applicant_type == "Customer":
		return frappe.db.get_value("Customer", applicant, "email_id") or ""
	elif applicant_type == "Employee":
		return frappe.db.get_value("Employee", applicant, "personal_email") or frappe.db.get_value(
			"Employee", applicant, "company_email"
		) or ""
	return ""


def _get_applicant_name(applicant_type, applicant):
	if applicant_type == "Customer":
		return frappe.db.get_value("Customer", applicant, "customer_name") or applicant
	elif applicant_type == "Employee":
		return frappe.db.get_value("Employee", applicant, "employee_name") or applicant
	return applicant


@frappe.whitelist()
def get_applicant_details(applicant_type: str, applicant: str):
	frappe.has_permission("Process Loan Statement of Accounts", throw=True)
	return {
		"applicant_name": _get_applicant_name(applicant_type, applicant),
		"email": get_applicant_email(applicant_type, applicant),
	}


@frappe.whitelist()
def fetch_applicants(company: str, applicant_type: str, collection_based_on: str, loan_product: str | None = None):
	frappe.has_permission("Process Loan Statement of Accounts", throw=True)

	filters = {"company": company, "applicant_type": applicant_type, "docstatus": 1}
	if collection_based_on == "Loan Product":
		if not loan_product:
			frappe.throw(_("Please select a Loan Product."))
		filters["loan_product"] = loan_product

	applicants = frappe.get_all(
		"Loan",
		filters=filters,
		fields=["applicant", "applicant_name"],
		group_by="applicant",
	)

	applicant_list = []
	for a in applicants:
		applicant_list.append(
			{
				"applicant_type": applicant_type,
				"applicant": a.applicant,
				"applicant_name": a.applicant_name,
				"email": get_applicant_email(applicant_type, a.applicant),
			}
		)
	return applicant_list


@frappe.whitelist()
def download_statements(document_name: str):
	doc = frappe.get_doc("Process Loan Statement of Accounts", document_name)
	doc.check_permission("read")
	report = get_report_pdf(doc)
	if report:
		frappe.local.response.filename = doc.name + ".pdf"
		frappe.local.response.filecontent = report
		frappe.local.response.type = "download"


@frappe.whitelist()
def send_emails(document_name: str, from_scheduler: bool = False):
	doc = frappe.get_doc("Process Loan Statement of Accounts", document_name)
	doc.check_permission()
	report = get_report_pdf(doc, consolidated=False)

	if not report:
		return False

	entry_by_applicant = {e.applicant: e for e in doc.applicants}

	for applicant, report_pdf in report.items():
		entry = entry_by_applicant[applicant]
		recipients, cc = get_recipients_and_cc(entry, doc)
		if not recipients:
			continue

		context = get_context(entry, doc)
		filename = frappe.render_template(doc.pdf_name, context)
		subject = frappe.render_template(doc.subject, context)
		message = frappe.render_template(doc.body, context)

		if doc.sender:
			sender_email = frappe.db.get_value("Email Account", doc.sender, "email_id")
		else:
			sender_email = frappe.session.user

		frappe.enqueue(
			queue="short",
			method=frappe.sendmail,
			recipients=recipients,
			sender=sender_email,
			cc=cc,
			subject=subject,
			message=message,
			now=True,
			reference_doctype="Process Loan Statement of Accounts",
			reference_name=document_name,
			attachments=[{"fname": filename + ".pdf", "fcontent": report_pdf}],
			expose_recipients="header",
		)

	if doc.enable_auto_email and from_scheduler:
		set_next_schedule_date(doc)

	doc.add_comment("Comment", "Emails sent on: " + frappe.utils.format_datetime(frappe.utils.now()))
	return True


def set_next_schedule_date(doc):
	new_to_date = getdate(today())
	if doc.frequency in ("Daily", "Weekly", "Biweekly"):
		days = {"Daily": 1, "Weekly": 7, "Biweekly": 14}
		new_to_date = add_days(new_to_date, days[doc.frequency])
	else:
		new_to_date = add_months(new_to_date, 1 if doc.frequency == "Monthly" else 3)

	new_from_date = add_months(new_to_date, -1 * (doc.filter_duration or 12))
	frappe.db.set_value(doc.doctype, doc.name, "start_date", new_to_date)
	frappe.db.set_value(doc.doctype, doc.name, "to_date", new_to_date)
	frappe.db.set_value(doc.doctype, doc.name, "from_date", new_from_date)


def send_auto_email():
	"""Scheduled task: send statements for all enabled docs due today."""
	selected = frappe.get_all(
		"Process Loan Statement of Accounts",
		filters={"enable_auto_email": 1, "start_date": today()},
		pluck="name",
	)
	for name in selected:
		send_emails(name, from_scheduler=True)
	return True
