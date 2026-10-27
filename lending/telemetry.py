"""Usage telemetry for Lending.

Data policy: an event describes how a feature is used, never the borrower or the
money involved. Properties are limited to counts, booleans and values from a fixed
vocabulary. Names, free text, amounts, rates, dates and anything that could
describe an applicant are stripped before the event leaves the site.
"""

from functools import wraps

import frappe
from frappe.database import savepoint
from frappe.utils import add_days, date_diff, getdate, today
from frappe.utils.telemetry import capture as _capture
from frappe.utils.telemetry import is_pulse_enabled as is_enabled
from frappe.utils.telemetry import site_age

APP = "lending"
ACTIVATION_WINDOW_DAYS = 30

# The only string properties that may be sent, each restricted to the standard
# Select options of the field it comes from. Anything else becomes "other".
FIXED_VOCABULARIES = {
	"applicant_type": {"Customer", "Employee", "Member", "Individual", "Business"},
	"repayment_frequency": {"Monthly", "Daily", "Weekly", "Bi-Weekly", "Quarterly", "One Time"},
	"repayment_method": {"Repay Fixed Amount per Period", "Repay Over Number of Periods"},
	"repayment_type": {
		"Normal Repayment",
		"Interest Waiver",
		"Penalty Waiver",
		"Charges Waiver",
		"Principal Adjustment",
		"Interest Carry Forward",
		"Write Off Recovery",
		"Security Deposit Adjustment",
		"Advance Payment",
		"Pre Payment",
		"Subsidy Adjustments",
		"Loan Closure",
		"Partial Settlement",
		"Full Settlement",
		"Write Off Settlement",
		"Charge Payment",
		"Penalty Capitalization",
		"Interest Capitalization",
		"Charges Capitalization",
		"Principal Capitalization",
	},
	"restructure_type": {"Normal Restructure", "Pre Payment", "Advance Payment"},
	"status": {"Open", "Approved", "Rejected", "Initiated"},
	"employment_type": {"Salaried", "Self-employed"},
	"foreclosure_type": {"Manual Foreclosure", "Internal Foreclosure"},
	"closure": {"requested", "closed"},
	"based_on": {"On Outstanding Principal", "On Total Payable Amount", "Flat"},
}


def _skip_context() -> bool:
	"""Don't record telemetry from automated / non-interactive runs."""
	return bool(
		frappe.flags.in_install
		or frappe.flags.in_migrate
		or frappe.flags.in_patch
		or frappe.flags.in_test
		or frappe.flags.in_import
	)


def _should_skip() -> bool:
	return _skip_context() or not is_enabled()


def sanitize_properties(properties: dict | None) -> dict:
	clean = {}
	for key, value in (properties or {}).items():
		if value is None or isinstance(value, bool | int | float):
			clean[key] = value
		elif isinstance(value, str) and key in FIXED_VOCABULARIES:
			clean[key] = value if value in FIXED_VOCABULARIES[key] else "other"
	return clean


def never_raise(fn):
	"""Log and swallow any error so telemetry never blocks a submit."""

	@wraps(fn)
	def wrapper(*args, **kwargs):
		try:
			return fn(*args, **kwargs)
		except Exception:
			frappe.log_error(title="Lending telemetry failed")

	return wrapper


def capture(event: str, properties: dict | None = None) -> None:
	"""Record a lending usage event (fires on every occurrence)."""
	if _should_skip():
		return

	_capture(event, APP, properties=sanitize_properties(properties))
	_track_conversion()


MILESTONE_DOCTYPE = "Lending Telemetry Milestone"


def _claim_milestone(event: str) -> bool:
	claimed = False

	with savepoint(catch=Exception):
		frappe.get_doc({"doctype": MILESTONE_DOCTYPE, "event": event}).insert(ignore_permissions=True)
		claimed = True

	return claimed


def _release_milestone(event: str) -> None:
	frappe.db.delete(MILESTONE_DOCTYPE, {"event": event})


def _claim_and_send(event: str, send) -> bool:
	"""Claim a once-only event, then send it. A failed send gives the claim back
	so a later attempt can still send the event. Returns True if it was sent."""
	if not _claim_milestone(event):
		return False

	try:
		send()
	except Exception:
		_release_milestone(event)
		raise

	return True


def capture_first(event: str, properties: dict | None = None, drives_conversion: bool = True) -> None:
	"""Fire once per site, and only while the site is young.

	Scheduler-run processes pass drives_conversion=False, as no user is involved.
	"""
	if _should_skip():
		return

	age = site_age()
	if not age or age > ACTIVATION_WINDOW_DAYS:
		return

	properties = {"day_since_install": age, **(properties or {})}
	sent = _claim_and_send(event, lambda: _capture(event, APP, properties=sanitize_properties(properties)))

	# Outside the claim: a conversion failure must not give back an event already sent.
	if sent and drives_conversion:
		_track_conversion()


# ---- Conversion --------------------------------------------------------------
# A site is "converted" if it still sends usage events more than 14 days after
# its first one. `first_capture` is never sent, its creation time starts the clock.

CONVERSION_WINDOW_DAYS = 14
FIRST_CAPTURE_MILESTONE = "first_capture"
CONVERSION_EVENT = "site_converted"


def _track_conversion() -> None:
	if frappe.db.exists(MILESTONE_DOCTYPE, CONVERSION_EVENT):
		return

	first_capture = frappe.db.get_value(MILESTONE_DOCTYPE, FIRST_CAPTURE_MILESTONE, "creation")
	if not first_capture:
		_claim_milestone(FIRST_CAPTURE_MILESTONE)
		return

	days_since_first_capture = date_diff(today(), first_capture)
	if days_since_first_capture <= CONVERSION_WINDOW_DAYS:
		return

	_claim_and_send(
		CONVERSION_EVENT,
		lambda: _capture(
			CONVERSION_EVENT,
			APP,
			properties={
				"days_since_first_capture": days_since_first_capture,
				"day_since_install": site_age(),
			},
		),
	)


# ---- Recurring usage ---------------------------------------------------------


@never_raise
def on_loan_lead_submit(doc, method=None):
	capture(
		"loan_lead_submitted",
		{
			"applicant_type": doc.applicant_type,
			"employment_type": doc.employment_type,
		},
	)
	capture_first("first_loan_lead_created")


@never_raise
def on_loan_application_submit(doc, method=None):
	capture(
		"loan_application_submitted",
		{
			"applicant_type": doc.applicant_type,
			"status": doc.status,
			"is_term_loan": bool(doc.is_term_loan),
			"is_secured_loan": bool(doc.is_secured_loan),
		},
	)
	capture_first("first_loan_application_created")


@never_raise
def on_loan_submit(doc, method=None):
	capture(
		"loan_booked",
		{
			"applicant_type": doc.applicant_type,
			"repayment_method": doc.repayment_method,
			"repayment_frequency": doc.repayment_frequency,
			"repayment_periods": doc.repayment_periods,
			"is_term_loan": bool(doc.is_term_loan),
			"is_secured_loan": bool(doc.is_secured_loan),
			"from_application": bool(doc.loan_application),
			"has_partner": bool(doc.get("loan_partner")),
			"is_imported": bool(doc.is_imported),
		},
	)
	capture_first("first_loan_booked")


@never_raise
def on_loan_disbursement_submit(doc, method=None):
	capture(
		"loan_disbursed",
		{
			"applicant_type": doc.applicant_type,
			"repayment_frequency": doc.repayment_frequency,
			"is_term_loan": bool(doc.is_term_loan),
			"has_partner": bool(doc.get("loan_partner")),
			"withhold_security_deposit": bool(doc.withhold_security_deposit),
			"is_imported": bool(doc.is_imported),
		},
	)
	capture_first("first_loan_disbursed")


@never_raise
def on_loan_repayment_submit(doc, method=None):
	capture(
		"loan_repayment_received",
		{
			"repayment_type": doc.repayment_type,
			"is_term_loan": bool(doc.is_term_loan),
			"is_npa": bool(doc.is_npa),
			"is_backdated": bool(doc.is_backdated),
			"is_bulk": bool(doc.bulk_repayment_log),
			"has_partner": bool(doc.get("loan_partner")),
			"is_imported": bool(doc.is_imported),
		},
	)
	capture_first("first_repayment_received")


@never_raise
def on_loan_restructure_submit(doc, method=None):
	capture(
		"loan_restructured",
		{
			"restructure_type": doc.restructure_type,
			"status": doc.status,
			"is_npa": bool(doc.is_npa),
			"waived_charges": bool(doc.waive_off_restructure_charges),
		},
	)


@never_raise
def on_loan_write_off_submit(doc, method=None):
	capture(
		"loan_written_off",
		{
			"is_npa": bool(doc.is_npa),
			"is_settlement": bool(doc.is_settlement_write_off),
		},
	)


# ---- Other recurring usage (table driven) ------------------------------------
# doctype -> (event, first-time event or None, property name -> doc field)
SUBMIT_EVENTS = {
	"Loan Adjustment": ("loan_adjustment_submitted", None, {"foreclosure_type": "foreclosure_type"}),
	"Loan Refund": (
		"loan_refund_submitted",
		None,
		{
			"applicant_type": "applicant_type",
			"is_excess_amount_refund": "is_excess_amount_refund",
			"is_security_amount_refund": "is_security_amount_refund",
		},
	),
	"Loan Balance Adjustment": ("loan_balance_adjusted", None, {}),
	"Loan Transfer": ("loan_transferred", None, {}),
	"Loan Security Assignment": ("loan_security_pledged", "first_loan_security_pledged", {}),
	"Loan Security Release": ("loan_security_released", None, {}),
	"Loan Security Deposit": ("loan_security_deposit_submitted", None, {}),
	"Bulk Repayment Log": ("bulk_repayment_submitted", None, {}),
}


@never_raise
def on_submit_event(doc, method=None):
	event, first_event, fields = SUBMIT_EVENTS[doc.doctype]
	capture(event, {prop: doc.get(field) for prop, field in fields.items()})
	if first_event:
		capture_first(first_event)


# ---- Lifecycle events not tied to a submit ------------------------------------


@never_raise
def on_loan_npa_log_insert(doc, method=None):
	capture(
		"loan_npa_status_changed",
		{"is_npa": bool(doc.npa), "is_manual": bool(doc.manual_npa), "is_delinked": bool(doc.delinked)},
	)


@never_raise
def on_loan_freeze_log_insert(doc, method=None):
	capture("loan_freeze_status_changed")


@never_raise
def on_collection_case_insert(doc, method=None):
	capture("collection_case_opened", {"applicant_type": doc.applicant_type, "status": doc.status})
	capture_first("first_collection_case_opened")


@never_raise
def capture_loan_closure(requested: bool) -> None:
	"""Called from the closure APIs after the status is written."""
	capture("loan_closure", {"closure": "requested" if requested else "closed"})
	if not requested:
		capture_first("first_loan_closed")


# Whitelisted API calls


@never_raise
def capture_charge_applied(based_on: str) -> None:
	capture("loan_charge_applied", {"based_on": based_on})


@never_raise
def capture_security_prices_updated(count: int) -> None:
	capture("loan_security_prices_bulk_updated", {"count": count})


@never_raise
def capture_repayment_schedule_previewed(repayment_frequency: str | None, tenure: int) -> None:
	capture(
		"repayment_schedule_previewed",
		{"repayment_frequency": repayment_frequency, "tenure": tenure},
	)


# ---- Scheduler-run process milestones -----------------------------------------
PROCESS_MILESTONES = {
	"Process Loan Interest Accrual": "first_interest_accrual_run",
	"Process Loan Demand": "first_demand_process_run",
	"Process Loan Classification": "first_classification_run",
	"Process Collection Dunning": "first_dunning_run",
	"Process Loan Accounting": "first_accounting_process_run",
	"Process Loan Security Shortfall": "first_security_shortfall_run",
}


@never_raise
def on_process_submit(doc, method=None):
	event = PROCESS_MILESTONES.get(doc.doctype)
	if event:
		capture_first(event, drives_conversion=False)


# ---- Activation milestones ---------------------------------------------------

# doctype -> event, sent the first time such a doc is created
CREATION_MILESTONES = {
	"Loan Product": "first_loan_product_created",
	"Loan Security Type": "loan_security_type_configured",
	"Loan Partner": "loan_partner_configured",
	"Dunning Rule": "dunning_rule_configured",
	"Loan Category": "loan_category_configured",
	"Loan Classification": "loan_classification_configured",
	"Loan Document Type": "loan_document_type_configured",
	"Loan Purpose": "loan_purpose_configured",
}


@never_raise
def on_milestone_insert(doc, method=None):
	event = CREATION_MILESTONES.get(doc.doctype)
	if event:
		capture_first(event)


# ---- Daily portfolio heartbeat -----------------------------------------------


@never_raise
def capture_daily_portfolio_pulse():
	if _should_skip():
		return

	live_statuses = ("Disbursed", "Active", "Partially Disbursed")
	active_loans = frappe.db.count("Loan", {"docstatus": 1, "status": ["in", live_statuses]})
	if not active_loans:
		# No loans yet, so a summary would only add noise.
		return

	# Runs just after midnight, so summarise the day that just ended.
	day = add_days(today(), -1)
	on_day = {"posting_date": day, "docstatus": 1}
	# Repayment and demand dates hold a time, so match the whole day, not midnight only.
	day_range = ["between", [f"{day} 00:00:00", f"{day} 23:59:59.999999"]]

	# Not user activity, so skip `capture` to keep it out of the conversion check.
	_capture(
		"portfolio_daily_summary",
		APP,
		properties={
			"active_loans": active_loans,
			"npa_loans": frappe.db.count("Loan", {"docstatus": 1, "is_npa": 1}),
			"overdue_loans": frappe.db.count("Loan", {"docstatus": 1, "days_past_due": [">", 0]}),
			"disbursements": frappe.db.count("Loan Disbursement", on_day),
			"repayments": frappe.db.count("Loan Repayment", {"docstatus": 1, "posting_date": day_range}),
			"demands_raised": frappe.db.count("Loan Demand", {"docstatus": 1, "demand_date": day_range}),
			# 0 = Monday .. 6 = Sunday
			"weekday": getdate(day).weekday(),
		},
	)
