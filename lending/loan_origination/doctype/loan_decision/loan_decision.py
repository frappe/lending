# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from lending.loan_origination.decisioning import (
	RECOMMENDED_TERM_FIELDS,
	UNDERWRITING,
	build_variable_context,
	downgrade_for_unscored,
	evaluate_strategy,
	latest_bureau_report,
	report_belongs_to,
	score_application,
	select_scorecard,
	select_strategy,
)


class LoanDecision(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		applicant: DF.DynamicLink | None
		applicant_type: DF.Literal["Customer", "Employee"]
		bureau_report: DF.Link | None
		bureau_score: DF.Int
		decision: DF.Literal["", "Approve", "Decline", "Refer"]
		decision_log: DF.LongText | None
		grade: DF.Data | None
		loan_application: DF.Link
		reason_codes: DF.SmallText | None
		recommended_amount: DF.Currency
		recommended_roi: DF.Percent
		recommended_tenure: DF.Int
		score: DF.Int
		scorecard: DF.Link | None
		strategy: DF.Link | None
		variable_snapshot: DF.Code | None
	# end: auto-generated types

	def validate(self):
		if not self.docstatus.is_draft():
			return

		application = self.get_application()

		self.resolve_bureau_report(application)
		self.resolve_strategy(application)
		self.resolve_scorecard(application)

		context = build_variable_context(application, self.bureau_report)
		self.bureau_score = cint(context.get("bureau_score"))

		log = []
		uncollected = self.apply_scorecard(context, log)
		self.apply_strategy(context, log)
		downgrade_for_unscored(self, uncollected, log)

		self.variable_snapshot = frappe.as_json(context)
		self.decision_log = "\n".join(log)

	def on_submit(self):
		self.write_back_to_application()

	def on_cancel(self):
		self.detach_from_application()

	def before_submit(self):
		if not self.decision:
			frappe.throw(
				_(
					"There is nothing to submit. No rule in {0} matched this applicant, so no decision was reached."
				).format(self.strategy or _("any strategy"))
			)

		self.assert_application_unchanged()
		self.assert_application_is_open()

	def assert_application_is_open(self):
		"""Submitting writes the decision onto the application below, deliberately past
		the permission and on-submit checks that guard it. Keep that write to an
		application that is still open, so it can never reach a submitted or cancelled
		one - by then the terms have been acted on and the Loan has been made from it.
		"""
		docstatus = frappe.db.get_value("Loan Application", self.loan_application, "docstatus")

		if docstatus == 0:
			return

		frappe.throw(
			_("{0} is no longer a draft, so a decision can no longer be recorded against it.").format(
				self.loan_application
			),
			title=_("Application Closed"),
		)

	def assert_application_unchanged(self):
		current = build_variable_context(self.get_application(), self.bureau_report)

		if current != json.loads(self.variable_snapshot or "{}"):
			frappe.throw(
				_(
					"{0} has changed since this decision was drafted. Save the decision again so it is made on what you are approving."
				).format(self.loan_application)
			)

	def get_application(self):
		return frappe.get_doc("Loan Application", self.loan_application, check_permission="read")

	def write_back_to_application(self):
		application = self.get_application()

		# A deliberate system write: an underwriter holds read on Loan Application and
		# nothing more, so these four fields are the only thing a decision may change on
		# it, and only while it is a draft (see assert_application_is_open).
		frappe.db.set_value(
			"Loan Application",
			self.loan_application,
			{"decision": self.name, **self.recommended_terms_for_application()},
		)

		application.add_comment("Comment", "\n".join(self.write_back_summary(application)))

	def recommended_terms_for_application(self):
		return {
			"recommended_roi": flt(self.recommended_roi),
			"recommended_amount": flt(self.recommended_amount),
			"recommended_tenure": cint(self.recommended_tenure),
		}

	def write_back_summary(self, application):
		lines = [_("{0} decided {1}.").format(self.name, self.decision)]

		if application.decision and application.decision != self.name:
			lines.append(_("Supersedes {0}.").format(application.decision))

		if self.reason_codes:
			lines.append(_("Reason codes: {0}.").format(", ".join(self.reason_codes.splitlines())))

		terms = self.recommended_terms(application)

		if terms:
			lines.append(
				_(
					"Recommended terms: {0}. Apply them on the application itself, so the repayment schedule is rebuilt with them."
				).format("; ".join(terms))
			)

		return lines

	def recommended_terms(self, application):
		recommendations = (
			(self.recommended_roi, application.rate_of_interest, _("rate of interest {0}, currently {1}")),
			(self.recommended_amount, application.loan_amount, _("loan amount capped at {0}, currently {1}")),
			(self.recommended_tenure, application.repayment_periods, _("tenure capped at {0}, currently {1}")),
		)

		return [
			message.format(recommended, current)
			for recommended, current, message in recommendations
			if recommended
		]

	def detach_from_application(self):
		application = self.get_application()

		if application.decision != self.name:
			return

		if not application.docstatus.is_draft():
			# assert_application_is_open, from the other end: the terms have been acted on
			# and the Loan has been made from them, so what governed them stays on the
			# application. Link integrity keeps a live decision and a live application tied
			# together, so this is only reached when something stepped around it.
			application.add_comment(
				"Comment",
				_(
					"{0} was cancelled, but this application is no longer a draft, so the decision it recorded stands."
				).format(self.name),
			)
			return

		frappe.db.set_value(
			"Loan Application",
			self.loan_application,
			{"decision": None, **dict.fromkeys(RECOMMENDED_TERM_FIELDS, 0)},
		)

		application.add_comment(
			"Comment",
			_("{0} was cancelled and no longer governs this application.").format(self.name),
		)

	def resolve_bureau_report(self, application):
		if self.bureau_report:
			self.validate_bureau_report(application)
			return

		report = latest_bureau_report(application.applicant_type, application.applicant)

		if report:
			self.bureau_report = report.name

	def validate_bureau_report(self, application):
		if report_belongs_to(self.bureau_report, application.applicant_type, application.applicant):
			return

		frappe.throw(
			_(
				"{0} is not a submitted Credit Bureau Report for {1}, so it cannot be used to decide this application."
			).format(self.bureau_report, application.applicant or _("this applicant")),
			title=_("Wrong Bureau Report"),
		)

	def resolve_strategy(self, application):
		if not self.strategy:
			self.strategy = select_strategy(UNDERWRITING, application.loan_product)

	def resolve_scorecard(self, application):
		if not self.scorecard:
			self.scorecard = select_scorecard(application.loan_product)

	def apply_scorecard(self, context, log):
		if not self.scorecard:
			self.score = 0
			self.grade = None
			self.flags.uncollected = []
			log.append(_("No scorecard applies to this loan product. Nothing was scored."))
			return []

		scored = score_application(self.scorecard, context)

		self.score = scored.score
		self.grade = scored.grade
		# Kept on flags so a dry run can reuse it instead of scoring the applicant again
		# for every candidate strategy it compares.
		self.flags.uncollected = scored.uncollected
		log.extend(scored.log)
		log.append(_("Score {0}, grade {1}.").format(scored.score, scored.grade or _("ungraded")))

		return scored.uncollected

	def apply_strategy(self, context, log):
		if not self.strategy:
			self.decision = None
			log.append(_("No underwriting strategy applies to this loan product."))
			return

		verdict = evaluate_strategy(self.strategy, context)

		self.decision = verdict.decision
		self.reason_codes = "\n".join(verdict.reason_codes)
		self.update({field: verdict.get(field) for field in RECOMMENDED_TERM_FIELDS})
		log.extend(verdict.log)
