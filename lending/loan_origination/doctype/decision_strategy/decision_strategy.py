# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from lending.loan_origination.decisioning import (
	ALLOWED_OPERATORS,
	APPLICANT_TYPES,
	DECLINE,
	KNOWN_VARIABLES,
	SCALAR_OPERATORS,
	is_number,
	split_values,
)


class DecisionStrategy(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_origination.doctype.decision_rule.decision_rule import DecisionRule

		disabled: DF.Check
		loan_product: DF.Link | None
		priority: DF.Int
		rules: DF.Table[DecisionRule]
		strategy_name: DF.Data
		strategy_type: DF.Literal["Pre-Qualification", "Knockout", "Underwriting"]
	# end: auto-generated types

	def validate(self):
		sequences = set()

		for rule in self.rules:
			self.validate_sequence(rule, sequences)
			self.validate_variable(rule)
			self.validate_operator(rule)
			self.validate_applicant_type(rule)
			self.validate_decline_reason(rule)

	def validate_sequence(self, rule, seen):
		if rule.sequence in seen:
			frappe.throw(
				_(
					"Row {0}: sequence {1} is already in use. The first matching rule wins, so two rules sharing a sequence have no defined order."
				).format(rule.idx, rule.sequence)
			)

		seen.add(rule.sequence)

	def validate_variable(self, rule):
		if rule.variable not in KNOWN_VARIABLES:
			frappe.throw(
				_(
					"Row {0}: {1} is not a variable the engine produces, so this rule could never match. Use one of: {2}."
				).format(rule.idx, rule.variable, ", ".join(KNOWN_VARIABLES))
			)

	def validate_operator(self, rule):
		if rule.operator not in ALLOWED_OPERATORS:
			frappe.throw(
				_("Row {0}: {1} is not a supported operator.").format(rule.idx, rule.operator)
			)

		if rule.operator == "between":
			self.validate_between_bounds(rule)
		elif rule.operator in SCALAR_OPERATORS:
			self.validate_scalar_value(rule)

	def validate_between_bounds(self, rule):
		bounds = split_values(rule.value)

		if len(bounds) != 2:
			frappe.throw(
				_("Row {0}: a between rule needs two comma separated values, such as 600,750.").format(
					rule.idx
				)
			)

		# Before comparing them: flt() turns anything unparseable into 0, so without this
		# a rule reading "low,high" would save as 0 > 0 and then match only 0 <= x <= 0.
		for bound in bounds:
			if not is_number(bound):
				frappe.throw(
					_(
						"Row {0}: a between rule compares by size, so {1} has to be a number. Write 100000 rather than 100,000."
					).format(rule.idx, bound)
				)

		if flt(bounds[0]) > flt(bounds[1]):
			frappe.throw(
				_("Row {0}: the lower bound {1} is above the upper bound {2}.").format(
					rule.idx, bounds[0], bounds[1]
				)
			)

	def validate_scalar_value(self, rule):
		if not is_number(rule.value):
			frappe.throw(
				_(
					"Row {0}: {1} compares by size, so {2} has to be a number. Write 100000 rather than 100,000."
				).format(rule.idx, rule.operator, rule.value)
			)

	def validate_applicant_type(self, rule):
		allowed = APPLICANT_TYPES.get(self.strategy_type)

		if not allowed or rule.variable != "applicant_type":
			return

		for value in split_values(rule.value):
			if value not in allowed:
				frappe.throw(
					_(
						"Row {0}: a {1} strategy only ever sees applicant types {2}. {3} belongs to the other stage, so this rule would never match."
					).format(rule.idx, self.strategy_type, ", ".join(allowed), value)
				)

	def validate_decline_reason(self, rule):
		if rule.outcome == DECLINE and not rule.reason_code:
			frappe.throw(
				_("Row {0}: a Decline rule needs a reason code the applicant can be told.").format(
					rule.idx
				)
			)
