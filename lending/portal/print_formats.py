# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Print Formats behind the borrower's two downloads.

Run once with:
	bench --site <site> execute lending.portal.print_formats.build

PORTAL_PLAN.md section 6.10 asks for the layout to live in a Print Format so that
changing it stays a design job rather than a code job. These records hold the layout;
lending/portal/downloads.py supplies the numbers and turns the result into a PDF.

One compromise is worth naming. A Print Format normally renders one document, and
neither of these is a document: a statement is a report over a date range, and a
certificate is a sum over many Loan Repayment rows. So `doc_type` is set to Loan
because a Print Format record requires one, and the template reads the context that
downloads passes rather than a `doc`. Opening either from a Loan form would render
an empty shell, which is why both are marked disabled -- they are reached only
through the portal, never from the desk print menu.

`Print Format` is in the `fixtures` list in hooks.py, so these travel with the app.
"""

import frappe

MODULE = "Loan Management"
DOCTYPE = "Loan"

STATEMENT_FORMAT = "Loan Statement of Account"
CERTIFICATE_FORMAT = "Loan Interest Certificate"

# Shared by both templates. Inlined because a PDF is rendered without the site's
# stylesheets, so anything not in the document itself is simply absent.
STYLE = """
<style>
	.portal-doc { font-family: sans-serif; color: #171717; font-size: 12px; }
	.portal-doc h1 { font-size: 19px; margin: 0 0 2px; }
	.portal-doc .muted { color: #7c7c7c; }
	.portal-doc .head { border-bottom: 2px solid #171717; padding-bottom: 10px; margin-bottom: 14px; }
	.portal-doc .head td { vertical-align: bottom; }
	/* The lender's own logo, at a height a letterhead can carry. get_pdf runs the
	   HTML through scrub_urls, so the relative path an Attach Image field holds is
	   absolute by the time wkhtmltopdf fetches it. */
	.portal-doc .logo { height: 34px; max-width: 190px; }
	.portal-doc .meta { margin-bottom: 16px; }
	.portal-doc .meta td { padding: 2px 16px 2px 0; }
	.portal-doc table.rows { width: 100%; border-collapse: collapse; }
	.portal-doc table.rows th {
		text-align: left; font-size: 11px; color: #7c7c7c; font-weight: 500;
		border-bottom: 1px solid #ededed; padding: 6px 8px;
	}
	.portal-doc table.rows td { padding: 7px 8px; border-bottom: 1px solid #f3f3f3; }
	.portal-doc table.rows td.num, .portal-doc table.rows th.num { text-align: right; }
	.portal-doc .totals { margin-top: 14px; width: 100%; border-collapse: collapse; }
	.portal-doc .totals td { padding: 6px 8px; }
	.portal-doc .totals tr:last-child td { border-top: 2px solid #171717; font-weight: 600; }
	.portal-doc .note {
		margin-top: 18px; padding: 10px 12px; background: #f8f8f8;
		border-left: 3px solid #ededed; font-size: 11px; color: #525252;
	}
	.portal-doc .stamp {
		display: inline-block; padding: 3px 8px; border-radius: 3px;
		background: #fdf8ed; color: #bb6f0c; font-size: 11px; font-weight: 600;
	}
	.portal-doc .foot {
		margin-top: 22px; padding-top: 10px; border-top: 1px solid #ededed;
		font-size: 10px; color: #7c7c7c;
	}
</style>
"""

HEAD = """
<table class="head" width="100%">
	<tr>
		<td><h1>{{ title }}</h1><div class="muted">{{ subtitle }}</div></td>
		<td align="right">
			{%- if brand_logo -%}
				<img class="logo" src="{{ brand_logo }}" alt="{{ brand_name }}">
			{%- else -%}
				<strong>{{ brand_name }}</strong>
			{%- endif -%}
		</td>
	</tr>
</table>

<table class="meta">
	<tr><td class="muted">Borrower</td><td><strong>{{ holder_name }}</strong></td></tr>
	<tr><td class="muted">Period</td><td>{{ period }}</td></tr>
	{% if accounts %}
	<tr>
		<td class="muted">Accounts</td>
		<td>{% for row in accounts %}{{ row.value }}{% if not loop.last %}, {% endif %}{% endfor %}</td>
	</tr>
	{% endif %}
</table>
"""

FOOT = """
<div class="foot">
	Generated on {{ generated_on }}. This document is issued electronically and is
	valid without a signature. For any query please contact
	{{ brand_name }}{% if support_email %} at {{ support_email }}{% endif %}.
</div>
"""

STATEMENT_HTML = (
	STYLE
	+ '<div class="portal-doc">'
	+ HEAD
	+ """
{% if rows %}
<table class="rows">
	<thead>
		<tr>
			<th>Date</th><th>Particulars</th><th>Type</th>
			<th class="num">Amount</th><th class="num">Balance</th>
		</tr>
	</thead>
	<tbody>
		{% for row in rows %}
		<tr>
			<td>{{ row.date }}</td>
			<td>{{ row.label }}</td>
			<td>{{ row.direction }}</td>
			<td class="num">{{ row.amount }}</td>
			<td class="num">{{ row.balance }}</td>
		</tr>
		{% endfor %}
	</tbody>
</table>

<table class="totals">
	{% for row in totals %}
	<tr><td class="muted">{{ row.label }}</td><td align="right">{{ row.value }}</td></tr>
	{% endfor %}
</table>
{% else %}
<p class="muted">There are no entries in this period.</p>
{% endif %}
"""
	+ FOOT
	+ "</div>"
)

CERTIFICATE_HTML = (
	STYLE
	+ '<div class="portal-doc">'
	+ HEAD
	+ """
<p><span class="stamp">{{ kind }}</span></p>

{% if rows %}
<table class="rows">
	<thead><tr><th>Head</th><th class="num">Amount</th></tr></thead>
	<tbody>
		{% for row in rows %}
		<tr><td>{{ row.label }}</td><td class="num">{{ row.value }}</td></tr>
		{% endfor %}
	</tbody>
</table>
{% else %}
<p class="muted">No amounts were paid in this financial year.</p>
{% endif %}

<div class="note">{{ disclaimer }}</div>
"""
	+ FOOT
	+ "</div>"
)

FORMATS = (
	(STATEMENT_FORMAT, STATEMENT_HTML),
	(CERTIFICATE_FORMAT, CERTIFICATE_HTML),
)


def upsert(name: str, html: str) -> str:
	if frappe.db.exists("Print Format", name):
		fmt = frappe.get_doc("Print Format", name)
	else:
		fmt = frappe.new_doc("Print Format")
		fmt.name = name

	fmt.update(
		{
			"doc_type": DOCTYPE,
			"module": MODULE,
			"print_format_type": "Jinja",
			"custom_format": 1,
			"standard": "No",
			# Kept out of the desk print menu: without the context downloads
			# passes, this template renders an empty page.
			"disabled": 1,
			"html": html,
		}
	)
	fmt.save(ignore_permissions=True)

	return fmt.name


def build():
	names = [upsert(name, html) for name, html in FORMATS]
	frappe.db.commit()  # nosemgrep

	for name in names:
		print(f"upserted Print Format {name}")

	return names
