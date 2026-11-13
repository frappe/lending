# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# Reuses the statement page endpoints so the PDF inherits their ownership scoping.

import re

import frappe
from frappe import _
from frappe.utils import nowdate
from frappe.utils.pdf import get_pdf

from lending.portal.core import long_date
from lending.portal.print_formats import CERTIFICATE_FORMAT, STATEMENT_FORMAT
from lending.portal.statement import get_certificate_page, get_statement_page

# A filename reaches the browser in a header, so it carries nothing that needs quoting.
UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def render(print_format: str, context: dict) -> str:
	html = frappe.db.get_value("Print Format", print_format, "html")
	if not html:
		frappe.throw(
			_("The {0} layout is missing. Please ask us to set it up.").format(print_format)
		)

	return frappe.render_template(html, context)  # nosemgrep


def as_download(html: str, filename: str):
	frappe.local.response.filename = UNSAFE_IN_FILENAME.sub("-", filename)
	frappe.local.response.filecontent = get_pdf(html)
	frappe.local.response.type = "pdf"


@frappe.whitelist()
def download_statement():
	payload = get_statement_page()
	period = _("{0} to {1}").format(
		long_date(payload["from_date"]), long_date(payload["to_date"])
	)

	html = render(
		STATEMENT_FORMAT,
		{
			"title": _("Statement of account"),
			"subtitle": payload.get("rows_note", ""),
			"brand_name": payload.get("brand_name", ""),
			"brand_logo": payload.get("brand_logo", ""),
			"support_email": payload.get("support_email", ""),
			"holder_name": payload.get("holder_name", ""),
			"period": period,
			"accounts": payload.get("accounts") or [],
			"rows": payload.get("rows") or [],
			"totals": payload.get("totals") or [],
			"generated_on": long_date(nowdate()),
		},
	)

	as_download(html, f"statement-{payload['from_date']}-to-{payload['to_date']}.pdf")


@frappe.whitelist()
def download_certificate():
	payload = get_certificate_page()

	html = render(
		CERTIFICATE_FORMAT,
		{
			"title": _("Interest certificate"),
			"subtitle": payload.get("rows_note", ""),
			"brand_name": payload.get("brand_name", ""),
			"brand_logo": payload.get("brand_logo", ""),
			"support_email": payload.get("support_email", ""),
			"holder_name": payload.get("holder_name", ""),
			"period": payload.get("year_label", ""),
			"accounts": payload.get("accounts") or [],
			"rows": payload.get("rows") or [],
			"kind": payload.get("kind", ""),
			"disclaimer": payload.get("disclaimer", ""),
			"generated_on": long_date(nowdate()),
		},
	)

	year = (payload.get("year_label") or "").replace(" ", "-").lower()
	as_download(html, f"interest-certificate-{year}.pdf")
