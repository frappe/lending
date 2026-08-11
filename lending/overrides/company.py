import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.utils import getdate, nowdate


def validate_loan_tables(doc, method=None):
<<<<<<< HEAD
	loan_classification_ranges = []
=======
	validate_gl_consolidation_start_date(doc)
	loan_classification_ranges = set()
>>>>>>> 4d20ab3 (fix: handle GL consolidation start date and repost across boundary)
	for d in doc.loan_classification_ranges:
		if (d.classification_code, d.is_written_off) not in loan_classification_ranges:
			loan_classification_ranges.append((d.classification_code, d.is_written_off))
		else:
			frappe.throw(
				_("Classification {0} added multiple times").format(frappe.bold(d.classification_code))
			)

	irac_provisioning_configurations = []
	for d in doc.irac_provisioning_configuration:
		if (d.classification_code, d.security_type) not in irac_provisioning_configurations:
			irac_provisioning_configurations.append((d.classification_code, d.security_type))
		else:
			frappe.throw(
				_("Classification {0} with security type {1} added multiple times").format(
					frappe.bold(d.classification_code), frappe.bold(d.security_type)
				)
			)
<<<<<<< HEAD
=======
		irac_provisioning_configurations.add(key)


def validate_gl_consolidation_start_date(doc):
	"""Start date can be any future date, including mid-month -- each loan's first period runs from
	the start date to that month's end (a partial first month), then full calendar months after.
	Just needs to be after existing daily GL, so nothing already posted is disturbed."""
	if not doc.get("loan_gl_consolidation") or not doc.get("loan_gl_consolidation_start_date"):
		return

	start_date = getdate(doc.loan_gl_consolidation_start_date)

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
				"({1}), so existing daily GL is left untouched and only new activity is "
				"consolidated."
			).format(start_date, getdate(last_gl_date))
		)

	if start_date <= getdate(nowdate()):
		frappe.throw(
			_(
				"Loan GL Consolidation Start Date {0} must be a future date. Existing GL up to "
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
>>>>>>> 4d20ab3 (fix: handle GL consolidation start date and repost across boundary)
