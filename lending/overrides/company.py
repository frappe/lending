import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.utils import get_first_day, getdate, nowdate


def validate_loan_tables(doc, method=None):
	validate_gl_consolidation_start_date(doc)
	loan_classification_ranges = set()
	for d in doc.loan_classification_ranges:
		key = (d.classification_code, d.is_written_off)
		if key in loan_classification_ranges:
			frappe.throw(
				_("Classification {0} added multiple times").format(frappe.bold(d.classification_code))
			)
		loan_classification_ranges.add(key)

	irac_provisioning_configurations = set()
	for d in doc.irac_provisioning_configuration:
		key = (d.classification_code, d.security_type)
		if key in irac_provisioning_configurations:
			frappe.throw(
				_("Classification {0} with security type {1} added multiple times").format(
					frappe.bold(d.classification_code), frappe.bold(d.security_type)
				)
			)
		irac_provisioning_configurations.add(key)


def validate_gl_consolidation_start_date(doc):
	"""Keep GL consolidation clean by only allowing it to start from a future month.

	Enabling it mid-stream would leave daily GL already posted for the on/after-start period
	un-consolidated (it stays daily and the job never sees it). Requiring a first-of-month start
	that is later than the last posted loan GL means every consolidated month starts empty, so
	prior months stay daily and every new month consolidates -- no data migration needed.
	"""
	if not doc.get("loan_gl_consolidation") or not doc.get("loan_gl_consolidation_start_date"):
		return

	start_date = getdate(doc.loan_gl_consolidation_start_date)

	if start_date != get_first_day(start_date):
		frappe.throw(
			_("Loan GL Consolidation Start Date must be the first day of a month, e.g. {0}.").format(
				get_first_day(start_date)
			)
		)

	# Only enforce the "future" rule when the setting is being turned on or the date is changed,
	# so saving an unrelated Company field later does not fail.
	before = doc.get_doc_before_save()
	unchanged = (
		before
		and before.get("loan_gl_consolidation")
		and getdate(before.get("loan_gl_consolidation_start_date") or "1900-01-01") == start_date
	)
	if unchanged:
		return

	last_gl_date = last_posted_loan_gl_date(doc.name)
	if last_gl_date and start_date <= getdate(last_gl_date):
		frappe.throw(
			_(
				"Loan GL Consolidation Start Date {0} must be after the last posted loan GL "
				"({1}). Set it to the first day of a future month so existing daily GL is left "
				"untouched and only new months are consolidated."
			).format(start_date, getdate(last_gl_date))
		)

	if start_date <= getdate(nowdate()):
		frappe.throw(
			_(
				"Loan GL Consolidation Start Date {0} must be a future month. Existing GL up to "
				"today stays daily; consolidation applies only from the start date onward."
			).format(start_date)
		)


def last_posted_loan_gl_date(company):
	"""Latest posting date of any Loan Interest Accrual / Loan Demand GL for the company."""
	gl = frappe.qb.DocType("GL Entry")
	result = (
		frappe.qb.from_(gl)
		.select(gl.posting_date)
		.where(
			(gl.company == company)
			& (gl.voucher_type.isin(["Loan Interest Accrual", "Loan Demand"]))
			& (gl.is_cancelled == 0)
		)
		.orderby(gl.posting_date, order=Order.desc)
		.limit(1)
		.run(pluck=True)
	)
	return result[0] if result else None
