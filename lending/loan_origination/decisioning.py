# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from operator import eq, ge, gt, le, lt, ne

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

APPROVE = "Approve"
REFER = "Refer"
DECLINE = "Decline"

PRE_QUALIFICATION = "Pre-Qualification"
KNOCKOUT = "Knockout"
UNDERWRITING = "Underwriting"

PREQUALIFICATION_STATUS = {
	APPROVE: "Pre-Qualified",
	REFER: "Referred",
	DECLINE: "Not Pre-Qualified",
}

COMPARISONS = {
	">": gt,
	">=": ge,
	"<": lt,
	"<=": le,
	"==": eq,
	"!=": ne,
}

MEMBERSHIP_OPERATORS = ("in", "not in")

ALLOWED_OPERATORS = (*COMPARISONS, *MEMBERSHIP_OPERATORS, "between")

SCALAR_OPERATORS = (">", ">=", "<", "<=")

APPLICANT_TYPES = {
	PRE_QUALIFICATION: ("Individual", "Business"),
	KNOCKOUT: ("Individual", "Business"),
	UNDERWRITING: ("Customer", "Employee"),
}

KNOWN_VARIABLES = (
	"age",
	"applicant_type",
	"bureau_score",
	"dti_ratio",
	"employment_type",
	"existing_obligations",
	"foir_ratio",
	"loan_amount",
	"loan_product",
	"ltv_ratio",
	"monthly_income",
	"proposed_emi",
	"rate_of_interest",
	"tenure",
)

LOAN_LEAD = "Loan Lead"

PRODUCT_AGNOSTIC = ("in", ["", None])

BUREAU_FIELDS = ["name", "score", "total_emi"]

RECOMMENDED_TERM_FIELDS = ("recommended_roi", "recommended_amount", "recommended_tenure")


def build_variable_context(source, bureau_report=None):
	context = {}

	_put(context, "loan_amount", _positive(source.loan_amount))

	if source.doctype == LOAN_LEAD:
		lead = source
		_put(context, "tenure", _positive(source.proposed_tenure))
	else:
		lead = _originating_lead(source)
		_put(context, "tenure", _positive(source.repayment_periods))
		_put(context, "rate_of_interest", _positive(source.rate_of_interest))
		_put(context, "proposed_emi", _positive(source.repayment_amount))
		_put(context, "ltv_ratio", _loan_to_value(source))

	_put(context, "applicant_type", source.get("applicant_type"))
	_put(context, "loan_product", source.get("loan_product"))

	if lead:
		_put(context, "monthly_income", _positive(lead.income))
		_put(context, "age", _positive(lead.age))
		_put(context, "employment_type", lead.employment_type)

	_add_bureau_variables(context, source, bureau_report, lead)
	_add_derived_ratios(context)

	return context


def run_strategy(doc, strategy_type=None):
	doc.check_permission("write")

	context = build_variable_context(doc)
	strategy = select_strategy(strategy_type, context.get("loan_product"))

	if not strategy:
		_record_no_strategy(doc, strategy_type, context.get("loan_product"))
		return None

	verdict = evaluate_strategy(strategy, context)
	verdict.strategy = strategy

	if strategy_type == KNOCKOUT:
		_enforce_knockout(verdict)

	_record_run(doc, verdict)

	if strategy_type == PRE_QUALIFICATION:
		_record_pre_qualification(doc, verdict)

	return verdict


def _enforce_knockout(verdict):
	"""A knockout is a hard gate, so it fails closed. Declining stops the transition,
	and so does a Decline rule that could not be evaluated at all: clearing an
	applicant because the data needed to reject them was never collected is not a pass.
	"""
	if verdict.decision == DECLINE:
		frappe.throw(
			_("Knockout rules declined this applicant. {0}").format(
				", ".join(verdict.reason_codes) or _("No reason code was recorded.")
			),
			title=_("Knockout Declined"),
		)

	if verdict.unverified_declines:
		frappe.throw(
			_(
				"This applicant cannot clear the knockout rules yet. {0} was not collected, so the rules that reject on it could not be checked."
			).format(", ".join(sorted(set(verdict.unverified_declines)))),
			title=_("Knockout Incomplete"),
		)


def run_pre_qualification_rules(doc):
	run_strategy(doc, PRE_QUALIFICATION)


def run_knockout_rules(doc):
	run_strategy(doc, KNOCKOUT)


def select_strategy(strategy_type, loan_product=None):
	filters = {"disabled": 0}

	if strategy_type:
		filters["strategy_type"] = strategy_type

	return _for_loan_product(
		"Decision Strategy", filters, "priority desc, modified desc", loan_product
	)


def select_scorecard(loan_product=None):
	return _for_loan_product("Scorecard", {}, "modified desc", loan_product)


def _for_loan_product(doctype, filters, order_by, loan_product):
	products = [loan_product, PRODUCT_AGNOSTIC] if loan_product else [PRODUCT_AGNOSTIC]

	for product in products:
		matches = frappe.get_all(
			doctype,
			filters={**filters, "loan_product": product},
			pluck="name",
			order_by=order_by,
			limit=1,
		)

		if matches:
			return matches[0]

	return None


def _record_run(doc, verdict):
	headline = _("{0} returned {1}.").format(
		verdict.strategy, verdict.decision or _("no matching rule")
	)

	doc.add_comment("Comment", "\n".join([headline, *verdict.log]))


def _record_no_strategy(doc, strategy_type, loan_product):
	"""Say so on the document. A stage that checked no rule at all must not be
	indistinguishable from one where every rule passed.
	"""
	doc.add_comment(
		"Comment",
		_("No enabled {0} strategy applies to {1}, so no rule was checked.").format(
			_(strategy_type) if strategy_type else _("decision"),
			loan_product or _("this applicant"),
		),
	)


def _record_pre_qualification(doc, verdict):
	doc.db_set(
		{
			"prequalification_status": PREQUALIFICATION_STATUS.get(verdict.decision) or "",
			"prequalified_on": now_datetime(),
			"prequalification_reason_codes": "\n".join(verdict.reason_codes),
			"indicative_amount": flt(verdict.recommended_amount),
			"indicative_roi": flt(verdict.recommended_roi),
			"indicative_tenure": cint(verdict.recommended_tenure),
		}
	)


def score_application(scorecard_name, context):
	verdict = frappe._dict(
		score=cint(frappe.db.get_value("Scorecard", scorecard_name, "base_score")),
		grade=None,
		uncollected=[],
		log=[],
	)

	bands = _attribute_bands_of(scorecard_name)

	for band in bands:
		value = _numeric(context.get(band.attribute))

		if value is None or not flt(band.min_range) <= value <= flt(band.max_range):
			continue

		verdict.score += cint(band.points)
		verdict.log.append(
			_("{0} is {1}, inside {2} to {3}. {4} points.").format(
				band.attribute, value, band.min_range, band.max_range, band.points
			)
		)

	for attribute in sorted({band.attribute for band in bands}):
		if _numeric(context.get(attribute)) is None:
			verdict.uncollected.append(attribute)
			verdict.log.append(
				_("{0} scored nothing. It was not collected for this applicant.").format(attribute)
			)

	verdict.grade = _grade_for(scorecard_name, verdict.score)

	return verdict


def _attribute_bands_of(scorecard_name):
	return frappe.get_all(
		"Scorecard Attribute",
		filters={"parent": scorecard_name, "parenttype": "Scorecard"},
		fields=["attribute", "min_range", "max_range", "points"],
		order_by="attribute asc, min_range asc",
	)


def _grade_for(scorecard_name, score):
	bands = frappe.get_all(
		"Scorecard Grade Band",
		filters={"parent": scorecard_name, "parenttype": "Scorecard"},
		fields=["grade", "min_score", "max_score"],
		order_by="min_score asc",
	)

	for band in bands:
		if cint(band.min_score) <= score <= cint(band.max_score):
			return band.grade

	return None


def evaluate_strategy(strategy_name, context):
	verdict = frappe._dict(
		decision=None,
		reason_codes=[],
		matched_rule=None,
		skipped_variables=[],
		unverified_declines=[],
		log=[],
		**dict.fromkeys(RECOMMENDED_TERM_FIELDS),
	)

	for rule in _rules_of(strategy_name):
		if rule.variable not in context:
			verdict.skipped_variables.append(rule.variable)

			if rule.outcome == DECLINE:
				verdict.unverified_declines.append(rule.variable)

			verdict.log.append(
				_("Rule {0} skipped. {1} was not collected for this applicant.").format(
					rule.sequence, rule.variable
				)
			)
			continue

		if not _cmp(context[rule.variable], rule.operator, rule.value):
			verdict.log.append(
				_("Rule {0} did not match. {1} is {2}.").format(
					rule.sequence, rule.variable, context[rule.variable]
				)
			)
			continue

		_apply_match(verdict, rule)
		verdict.log.append(
			_("Rule {0} matched on {1}. Outcome {2}.").format(
				rule.sequence, rule.variable, rule.outcome
			)
		)

		if cint(rule.stop_on_match):
			break

	_downgrade_unverified_approval(verdict)

	return verdict


def downgrade_for_unscored(verdict, uncollected, log):
	"""An Approve reached without scoring every attribute the scorecard asks for is not an
	Approve. Shared, so a dry run and a saved Loan Decision cannot drift apart on it.
	"""
	if verdict.get("decision") != APPROVE or not uncollected:
		return

	verdict.decision = REFER
	log.append(_("Approve downgraded to Refer. {0} was not scored.").format(", ".join(uncollected)))


def _downgrade_unverified_approval(verdict):
	if verdict.decision != APPROVE or not verdict.skipped_variables:
		return

	verdict.decision = REFER
	verdict.log.append(
		_("Approve downgraded to Refer. {0} could not be checked.").format(
			", ".join(sorted(set(verdict.skipped_variables)))
		)
	)


def _apply_match(verdict, rule):
	if verdict.decision and verdict.decision != rule.outcome:
		verdict.log.append(
			_("Outcome {0} superseded by {1}. Its reason codes and terms are dropped.").format(
				verdict.decision, rule.outcome
			)
		)
		verdict.reason_codes = []
		verdict.update(dict.fromkeys(RECOMMENDED_TERM_FIELDS))

	verdict.decision = rule.outcome
	verdict.matched_rule = rule.name

	if rule.reason_code:
		verdict.reason_codes.append(rule.reason_code)

	_recommend(
		verdict,
		"recommended_roi",
		flt(rule.term_roi_override),
		_("Recommended rate of interest {0}."),
		_("Kept the higher recommended rate of interest. {0} would have priced the risk lower."),
		keep=max,
	)
	_recommend(
		verdict,
		"recommended_amount",
		flt(rule.term_amount_cap),
		_("Recommended amount capped at {0}."),
		_("Kept the tighter amount cap. {0} would have been looser."),
		keep=min,
	)
	_recommend(
		verdict,
		"recommended_tenure",
		cint(rule.term_tenure_cap),
		_("Recommended tenure capped at {0}."),
		_("Kept the tighter tenure cap. {0} would have been looser."),
		keep=min,
	)


def _recommend(verdict, field, value, message, superseded_message, keep):
	"""Two rules reaching the same outcome can each recommend terms. Keep the stricter of
	the two rather than whichever matched last, so a looser cap cannot silently void a
	tighter one. Caps take the lower value; the rate takes the higher, which is the one
	that prices the risk more conservatively.
	"""
	if not value:
		return

	current = verdict.get(field)

	if current and keep(current, value) == current:
		if value != current:
			verdict.log.append(superseded_message.format(value))

		return

	verdict[field] = value
	verdict.log.append(message.format(value))


def _cmp(lhs, operator, rhs):
	if operator not in ALLOWED_OPERATORS:
		frappe.throw(_("{0} is not a supported decision rule operator.").format(operator))

	if operator == "between":
		low, high = parse_bounds(rhs)
		return low <= flt(lhs) <= high

	if operator in MEMBERSHIP_OPERATORS:
		found = _member_of(lhs, rhs)
		return found if operator == "in" else not found

	return COMPARISONS[operator](*_comparable(lhs, rhs))


def parse_bounds(value):
	parts = split_values(value)

	if len(parts) != 2:
		frappe.throw(
			_("A between rule needs two comma separated values. {0} has {1}.").format(
				value, len(parts)
			)
		)

	return flt(parts[0]), flt(parts[1])


def split_values(value):
	return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _member_of(lhs, rhs):
	number = _numeric(lhs)
	text = str(lhs).strip()

	for token in split_values(rhs):
		if number is not None and _numeric(token) == number:
			return True

		if token == text:
			return True

	return False


def _comparable(lhs, rhs):
	left = _numeric(lhs)
	right = _numeric(rhs)

	if left is not None and right is not None:
		return left, right

	if left is not None:
		frappe.throw(
			_(
				"Rule value {0} is not a number, but {1} is. Write 100000 rather than 100,000."
			).format(rhs, lhs)
		)

	return str(lhs).strip(), str(rhs).strip()


def is_number(value):
	return _numeric(value) is not None


def _rules_of(strategy_name):
	return frappe.get_all(
		"Decision Rule",
		filters={"parent": strategy_name, "parenttype": "Decision Strategy"},
		fields=[
			"name",
			"sequence",
			"variable",
			"operator",
			"value",
			"outcome",
			"reason_code",
			"stop_on_match",
			"term_roi_override",
			"term_amount_cap",
			"term_tenure_cap",
		],
		order_by="sequence asc, idx asc",
	)


def _originating_lead(loan_application):
	lead_name = loan_application.get("loan_lead")

	if not lead_name:
		return None

	return frappe.db.get_value(
		LOAN_LEAD, lead_name, ["pan", "income", "age", "employment_type"], as_dict=True
	)


def _add_bureau_variables(context, source, bureau_report=None, lead=None):
	report = _report_by_name(bureau_report) if bureau_report else _report_for(source, lead)

	if not report:
		return

	_put(context, "bureau_score", _positive(report.score))
	context["existing_obligations"] = flt(report.total_emi)


def _report_for(source, lead=None):
	if source.doctype == LOAN_LEAD:
		return latest_bureau_report_for_pan(source.get("pan"))

	# A report pulled while the applicant was still a lead is filed against their PAN,
	# because there was no Customer yet to file it against. Underwriting has to be able
	# to reach it: otherwise every bureau rule is skipped rather than fired, and a
	# knockout that should stop the applicant never runs.
	return latest_bureau_report(
		source.get("applicant_type"), source.get("applicant")
	) or latest_bureau_report_for_pan(lead.pan if lead else None)


def _report_by_name(bureau_report):
	frappe.has_permission("Credit Bureau Report", "read", doc=bureau_report, throw=True)

	# docstatus, not just the name: a draft or cancelled report must never reach a
	# decision, whichever field on whichever document pointed at it.
	return frappe.db.get_value(
		"Credit Bureau Report", {"name": bureau_report, "docstatus": 1}, BUREAU_FIELDS, as_dict=True
	)


def report_belongs_to(bureau_report, applicant_type, applicant):
	"""The form filters the report picker to this applicant. That filter is client side,
	so the same constraint has to hold on anything that was posted to us.
	"""
	return bool(
		frappe.db.exists(
			"Credit Bureau Report",
			{
				"name": bureau_report,
				"docstatus": 1,
				"applicant_type": applicant_type,
				"applicant": applicant,
			},
		)
	)


def latest_bureau_report(applicant_type, applicant):
	if not (applicant_type and applicant):
		return None

	return _latest_report({"applicant_type": applicant_type, "applicant": applicant})


def latest_bureau_report_for_pan(pan):
	if not pan:
		return None

	return _latest_report({"pan": pan})


def _latest_report(filters):
	reports = frappe.get_list(
		"Credit Bureau Report",
		filters=dict(filters, docstatus=1),
		fields=BUREAU_FIELDS,
		order_by="report_date desc",
		limit=1,
	)

	return reports[0] if reports else None


def _add_derived_ratios(context):
	income = context.get("monthly_income")
	obligations = context.get("existing_obligations")
	proposed_emi = context.get("proposed_emi")

	if not income or obligations is None:
		return

	context["dti_ratio"] = flt(obligations) / flt(income)

	if proposed_emi is not None:
		context["foir_ratio"] = (flt(obligations) + flt(proposed_emi)) / flt(income)


def _loan_to_value(loan_application):
	if not cint(loan_application.get("is_secured_loan")):
		return None

	security_value = sum(
		flt(pledge.amount) for pledge in loan_application.get("proposed_pledges") or []
	)

	if not security_value:
		return None

	return flt(loan_application.loan_amount) / security_value


def _numeric(value):
	if value is None or isinstance(value, bool):
		return None

	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _put(context, key, value):
	if value is None or value == "":
		return

	context[key] = value


def _positive(value):
	value = flt(value)

	return value if value > 0 else None


APPLICANT_FIELDS = (
	"scorecard",
	"bureau_report",
	"bureau_score",
	"score",
	"grade",
	"variable_snapshot",
)

def _summary(decision, fields):
	return frappe._dict({field: decision.get(field) for field in fields})


def _check_dry_run_permission(loan_application, strategy=None, scorecard=None):
	frappe.has_permission("Loan Application", "read", doc=loan_application, throw=True)
	frappe.has_permission("Loan Decision", "create", throw=True)

	# Both are caller supplied, so neither is the form's business to vouch for.
	if strategy:
		frappe.has_permission("Decision Strategy", "read", doc=strategy, throw=True)

	if scorecard:
		frappe.has_permission("Scorecard", "read", doc=scorecard, throw=True)


def _dry_run(loan_application, strategy=None, scorecard=None, bureau_report=None):
	decision = frappe.new_doc("Loan Decision")
	decision.loan_application = loan_application
	decision.strategy = strategy
	decision.scorecard = scorecard
	decision.bureau_report = bureau_report
	decision.validate()

	return decision


@frappe.whitelist(methods=["POST"])
def compare_strategies(
	loan_application: str,
	strategy: str | None = None,
	scorecard: str | None = None,
	bureau_report: str | None = None,
):
	_check_dry_run_permission(loan_application, strategy, scorecard)

	loan_product = frappe.db.get_value("Loan Application", loan_application, "loan_product")

	# One dry run establishes what the engine sees, which every row below shares, and the
	# candidates are then only their rules against it. Running a whole decision per row
	# would reload the application and re-score the applicant for identical answers.
	baseline = _dry_run(loan_application, strategy, scorecard, bureau_report)
	context = frappe.parse_json(baseline.variable_snapshot or "{}")
	uncollected = baseline.flags.uncollected or []

	return frappe._dict(
		loan_application=loan_application,
		loan_product=loan_product,
		selected=baseline.strategy,
		rows=[
			_comparison_row(candidate, context, uncollected, baseline.strategy)
			for candidate in _candidate_strategies(loan_product)
		],
		**_summary(baseline, APPLICANT_FIELDS),
	)


def _candidate_strategies(loan_product):
	return frappe.get_all(
		"Decision Strategy",
		filters={
			"disabled": 0,
			"strategy_type": UNDERWRITING,
			"loan_product": ("in", [loan_product, "", None]),
		},
		fields=["name", "loan_product", "priority"],
		order_by="priority desc, modified desc",
	)


def _comparison_row(candidate, context, uncollected, selected):
	verdict = evaluate_strategy(candidate.name, context)
	downgrade_for_unscored(verdict, uncollected, verdict.log)

	return frappe._dict(
		strategy=candidate.name,
		loan_product=candidate.loan_product,
		priority=candidate.priority,
		selected=candidate.name == selected,
		decision=verdict.decision,
		reason_codes=verdict.reason_codes,
		decision_log="\n".join(verdict.log),
		**{field: verdict.get(field) for field in RECOMMENDED_TERM_FIELDS},
	)
