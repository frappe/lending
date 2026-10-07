# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Collections & Delinquency Management.

Hooks onto ``Days Past Due Log`` doc_events to auto-open/escalate/resolve a
``Collection Case`` whenever a loan crosses a DPD classification bucket, and
drives Promise-to-Pay tracking, dunning, and hardship handoff to
``Loan Restructure``. Deliberately does not touch ``loan.py`` — all bucket
crossing detection is derived from ``Days Past Due Log`` + ``Loan Classification
Range``, mirroring how ``update_loan_and_customer_status`` already classifies DPD.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate, today

from lending.loan_management.doctype.loan.loan import get_classification_code_and_name


def on_dpd_log_upsert(doc, method=None):
	"""Registered on Days Past Due Log after_insert + on_update.

	Fires every time ``create_dpd_record`` saves a log (via
	``update_days_past_due_in_loans`` / ``repost_days_past_due_log``), so this
	is the single non-forking entry point for Collections instead of editing
	``loan.py`` directly.
	"""
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
		return

	loan_details = frappe.db.get_value(
		"Loan",
		doc.loan,
		["company", "applicant_type", "applicant", "loan_product", "status", "repayment_schedule_type"],
		as_dict=1,
	)
	if not loan_details:
		return

	posting_date = getdate(doc.posting_date) if doc.posting_date else today()

	latest_log = frappe.db.get_value(
		"Collection Case Log",
		{"loan": doc.loan},
		["posting_date", "to_bucket"],
		order_by="posting_date desc, creation desc",
		as_dict=True,
	)
	# repost_days_past_due_log re-walks historical dates, so a later call here
	# can carry an older posting_date than what's already on file; ignore it
	# rather than letting stale history flip a current case.
	if latest_log and posting_date < getdate(latest_log.posting_date):
		return

	days_past_due = get_loan_days_past_due(doc.loan, loan_details.repayment_schedule_type, doc.days_past_due)

	is_written_off = 1 if loan_details.status == "Written Off" else 0
	to_bucket_code, _to_bucket_name = get_classification_code_and_name(
		days_past_due, loan_details.company, is_written_off=is_written_off
	)
	from_bucket_code = latest_log.to_bucket if latest_log else None

	open_case = frappe.db.get_value(
		"Collection Case",
		{"loan": doc.loan, "status": ("not in", ["Resolved", "Closed"])},
		"name",
	)

	if to_bucket_code == from_bucket_code:
		# No new case/log event, but an open case's amounts still need to track
		# the loan within the bucket, or they go stale until the next crossing.
		if open_case and days_past_due > 0:
			refresh_case_amounts(open_case, doc.loan, days_past_due, posting_date)
		return

	if days_past_due <= 0:
		if open_case:
			resolve_case(doc.loan)
			create_collection_case_log(
				doc.loan, from_bucket_code, to_bucket_code or from_bucket_code, days_past_due,
				"Resolved", posting_date=posting_date,
			)
		return

	if not is_bucket_escalation(from_bucket_code, to_bucket_code, loan_details.company):
		return

	branch = get_applicant_branch(loan_details.applicant_type, loan_details.applicant)
	outstanding_amount = get_case_outstanding_amount(doc.loan, posting_date)

	case = get_or_create_case(
		loan=doc.loan,
		company=loan_details.company,
		branch=branch,
		loan_product=loan_details.loan_product,
		applicant_type=loan_details.applicant_type,
		applicant=loan_details.applicant,
		bucket=to_bucket_code,
		classification_code=to_bucket_code,
		days_past_due=days_past_due,
		outstanding_amount=outstanding_amount,
	)

	event = "Case Opened" if not open_case else "Bucket Escalated"
	create_collection_case_log(
		doc.loan, from_bucket_code, to_bucket_code, days_past_due, event, case.name,
		posting_date=posting_date,
	)


def get_loan_days_past_due(loan, repayment_schedule_type, log_days_past_due):
	"""For Line of Credit, DPD is the max across disbursements (as loan.py itself
	computes it), not just the one disbursement whose log triggered this hook."""
	if repayment_schedule_type != "Line of Credit":
		return log_days_past_due or 0

	rows = frappe.get_all(
		"Loan Disbursement",
		filters={"against_loan": loan, "docstatus": 1},
		fields=[{"MAX": "days_past_due"}],
		as_list=True,
	)
	return (rows[0][0] if rows else 0) or 0


def is_bucket_escalation(from_bucket_code, to_bucket_code, company):
	"""True only when the loan has moved to a strictly higher-ranked DPD bucket."""
	if not to_bucket_code:
		return False
	if not from_bucket_code:
		return True

	ranks = frappe._dict(
		frappe.get_all(
			"Loan Classification Range",
			filters={"parent": company},
			fields=["classification_code", "min_dpd_range"],
			as_list=1,
		)
	)

	return ranks.get(to_bucket_code, 0) > ranks.get(from_bucket_code, 0)


def get_applicant_branch(applicant_type, applicant):
	if applicant_type == "Employee":
		return frappe.db.get_value("Employee", applicant, "branch")
	return None


def refresh_case_amounts(case_name, loan, days_past_due, posting_date):
	"""Keep an open case's days_past_due/outstanding_amount current while the loan
	stays in the same bucket (e.g. a partial payment reduces DPD without crossing
	into a lower bucket)."""
	frappe.db.set_value(
		"Collection Case",
		case_name,
		{
			"days_past_due": days_past_due,
			"outstanding_amount": get_case_outstanding_amount(loan, posting_date),
		},
		update_modified=False,
	)


def get_case_outstanding_amount(loan, posting_date):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	amounts = calculate_amounts(loan, posting_date)
	return amounts.get("pending_principal_amount", 0) + amounts.get("interest_amount", 0)


def get_or_create_case(loan, company, branch, loan_product, applicant_type, applicant, bucket,
	classification_code, days_past_due, outstanding_amount):
	"""Upsert the single open Collection Case for a loan (one open case per loan)."""
	existing = frappe.db.get_value(
		"Collection Case",
		{"loan": loan, "status": ("not in", ["Resolved", "Closed"])},
	)

	if existing:
		case = frappe.get_doc("Collection Case", existing, for_update=True)
		is_new = False
	else:
		case = frappe.new_doc("Collection Case")
		case.loan = loan
		case.opened_on = today()
		case.status = "Open"
		is_new = True

	case.update(
		{
			"company": company,
			"branch": branch,
			"loan_product": loan_product,
			"applicant_type": applicant_type,
			"applicant": applicant,
			"bucket": bucket,
			"classification_code": classification_code,
			"days_past_due": days_past_due,
			"outstanding_amount": outstanding_amount,
		}
	)

	if is_new:
		case.assigned_agent = allocate_agent(company, branch, loan_product)

	case.save(ignore_permissions=True)
	return case


def resolve_case(loan, resolution_reason=None):
	existing = frappe.db.get_value(
		"Collection Case",
		{"loan": loan, "status": ("not in", ["Resolved", "Closed"])},
	)
	if not existing:
		return None

	case = frappe.get_doc("Collection Case", existing, for_update=True)
	case.status = "Resolved"
	case.closed_on = today()
	case.resolution_reason = resolution_reason or _("Days past due returned to 0")
	case.days_past_due = 0
	case.save(ignore_permissions=True)
	return case


def allocate_agent(company, branch, loan_product):
	"""Pool = enabled Users with role Loan Officer; round-robin by fewest open cases.
	Branch match only breaks ties among equally-loaded agents -- there is no
	reliable branch field on User to filter the pool by, so it can't exclude an
	agent who simply has no case history there yet."""
	pool = frappe.get_all(
		"Has Role",
		filters={"role": "Loan Officer", "parenttype": "User"},
		pluck="parent",
	)
	if not pool:
		return None

	enabled_pool = frappe.get_all(
		"User", filters={"name": ("in", pool), "enabled": 1}, pluck="name"
	)
	if not enabled_pool:
		return None

	open_case_counts = frappe._dict(
		frappe.get_all(
			"Collection Case",
			filters={"assigned_agent": ("in", enabled_pool), "status": ("not in", ["Resolved", "Closed"])},
			group_by="assigned_agent",
			fields=["assigned_agent", {"COUNT": "name"}],
			as_list=1,
		)
	)

	branch_agents = set()
	if branch:
		branch_agents = set(
			frappe.get_all(
				"Collection Case",
				filters={"assigned_agent": ("in", enabled_pool), "branch": branch},
				pluck="assigned_agent",
				distinct=True,
			)
		)

	return min(
		enabled_pool,
		key=lambda agent: (open_case_counts.get(agent, 0), agent not in branch_agents),
	)


def create_collection_case_log(loan, from_bucket, to_bucket, days_past_due, event,
	collection_case=None, process_collection_dunning=None, posting_date=None):
	"""UPSERT like create_dpd_record: one log per (loan, posting_date, event)."""
	posting_date = posting_date or today()

	if not collection_case:
		collection_case = frappe.db.get_value(
			"Collection Case",
			{"loan": loan, "status": ("not in", ["Resolved", "Closed"])},
		) or frappe.db.get_value("Collection Case", {"loan": loan}, order_by="creation desc")

	existing_log = frappe.db.get_value(
		"Collection Case Log",
		{"loan": loan, "posting_date": posting_date, "event": event},
	)
	if existing_log:
		log = frappe.get_doc("Collection Case Log", existing_log, for_update=True)
	else:
		log = frappe.new_doc("Collection Case Log")

	log.update(
		{
			"collection_case": collection_case,
			"loan": loan,
			"posting_date": posting_date,
			"from_bucket": from_bucket,
			"to_bucket": to_bucket,
			"days_past_due": days_past_due,
			"event": event,
			"process_collection_dunning": process_collection_dunning,
		}
	)
	log.save(ignore_permissions=True)
	return log


def pick_dunning_rule(company, loan_product, classification_code, days_past_due):
	"""Narrowest matching Dunning Rule: min_dpd <= dpd <= max_dpd, smallest range wins."""
	rules = frappe.get_all(
		"Dunning Rule",
		filters={
			"company": company,
			"disabled": 0,
			"min_dpd": ("<=", days_past_due),
			"max_dpd": (">=", days_past_due),
		},
		fields=["name", "loan_product", "classification_code", "min_dpd", "max_dpd", "channel",
			"communication_template", "cadence_days"],
	)

	matching = [
		r for r in rules
		if (not r.loan_product or r.loan_product == loan_product)
		and (not r.classification_code or r.classification_code == classification_code)
	]
	if not matching:
		return None

	matching.sort(key=lambda r: r.max_dpd - r.min_dpd)
	return matching[0]


def process_collection_dunning_batch(collection_cases, process_collection_dunning):
	for case_name in collection_cases:
		try:
			send_dunning_for_case(case_name, process_collection_dunning)
			if len(collection_cases) > 1:
				frappe.db.commit()
		except Exception:
			if len(collection_cases) == 1:
				raise
			frappe.log_error(
				title="Process Collection Dunning Error",
				message=frappe.get_traceback(),
				reference_doctype="Collection Case",
				reference_name=case_name,
			)
			frappe.db.rollback()


def send_dunning_for_case(case_name, process_collection_dunning):
	case = frappe.get_doc("Collection Case", case_name)

	# The case may have been resolved (e.g. a repayment) between when
	# on_submit selected it and when this batch/job actually runs.
	if case.status in ("Resolved", "Closed"):
		return

	rule = pick_dunning_rule(case.company, case.loan_product, case.classification_code, case.days_past_due)
	if not rule:
		return

	last_dunning_date = None
	for activity in reversed(case.activities):
		if activity.activity_type == "System Dunning":
			last_dunning_date = getdate(activity.activity_date)
			break

	# Against today, not the batch's nominal posting_date (often "yesterday") --
	# the activity below is stamped with today's date, so comparing against
	# posting_date would delay every reminder by a day.
	if last_dunning_date and add_days(last_dunning_date, rule.cadence_days) > getdate(today()):
		return

	sent = send_loan_notification(
		case.loan, case.applicant_type, case.applicant, rule.channel, rule.communication_template
	)

	case.append(
		"activities",
		{
			"activity_type": "System Dunning",
			"channel": rule.channel,
			"activity_date": nowdate(),
			"outcome": "",
			"template_used": rule.communication_template,
			"notes": _("Auto dunning via {0}").format(rule.name)
			if sent
			else _("Auto dunning via {0} failed: no recipient address on file").format(rule.name),
		},
	)
	case.save(ignore_permissions=True)

	if not sent:
		return

	create_collection_case_log(
		case.loan, case.bucket, case.bucket, case.days_past_due, "Dunning Sent",
		case.name, process_collection_dunning,
	)


def send_loan_notification(loan, applicant_type, applicant, channel, communication_template):
	"""Email is sent via frappe.sendmail; SMS/WhatsApp are logged as a Communication
	for an integration layer to pick up, since no gateway ships with lending.
	Returns False (not sent) only for an Email rule with no recipient on file."""
	template = frappe.get_doc("Email Template", communication_template)
	formatted = template.get_formatted_email({"loan": loan, "applicant": applicant})
	subject, message = formatted["subject"], formatted["message"]

	recipient = None
	if applicant_type == "Customer":
		recipient = frappe.db.get_value("Customer", applicant, "email_id")
	elif applicant_type == "Employee":
		recipient = frappe.db.get_value("Employee", applicant, "personal_email") or frappe.db.get_value(
			"Employee", applicant, "company_email"
		)

	if channel == "Email":
		if not recipient:
			return False
		frappe.sendmail(recipients=[recipient], subject=subject, message=message, reference_doctype="Loan", reference_name=loan)
	else:
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": channel,
				"subject": subject,
				"content": message,
				"reference_doctype": "Loan",
				"reference_name": loan,
				"sent_or_received": "Sent",
			}
		).insert(ignore_permissions=True)

	return True


@frappe.whitelist()
def launch_hardship(case_name: str, restructure_type: str) -> str:
	"""Create a Loan Restructure from a Collection Case, link it, and mark the case Hardship Requested."""
	frappe.has_permission("Collection Case", "write", doc=case_name, throw=True)

	case = frappe.get_doc("Collection Case", case_name)

	restructure = frappe.new_doc("Loan Restructure")
	restructure.loan = case.loan
	restructure.restructure_type = restructure_type
	restructure.restructure_date = nowdate()
	restructure.insert(ignore_permissions=True)

	case.linked_restructure = restructure.name
	case.status = "Hardship Requested"
	case.save(ignore_permissions=True)

	create_collection_case_log(
		case.loan, case.bucket, case.bucket, case.days_past_due, "Hardship Requested", case.name
	)

	return restructure.name
