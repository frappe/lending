# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from itertools import pairwise

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from lending.loan_origination.decisioning import KNOWN_VARIABLES


class Scorecard(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_origination.doctype.scorecard_attribute.scorecard_attribute import (
			ScorecardAttribute,
		)
		from lending.loan_origination.doctype.scorecard_grade_band.scorecard_grade_band import (
			ScorecardGradeBand,
		)

		attributes: DF.Table[ScorecardAttribute]
		base_score: DF.Int
		grade_bands: DF.Table[ScorecardGradeBand]
		loan_product: DF.Link | None
		scorecard_name: DF.Data
	# end: auto-generated types

	def validate(self):
		for row in self.attributes:
			self.validate_attribute(row)

		for attribute, rows in self.bands_by_attribute().items():
			validate_ranges(rows, "min_range", "max_range", attribute)

		validate_ranges(self.grade_bands, "min_score", "max_score", _("Grade Bands"))

	def validate_attribute(self, row):
		"""Checked the way a Decision Rule variable is. A misspelt attribute scores nothing
		and reads as uncollected, which quietly turns every Approve into a Refer, and the
		only trace of it is a line in the decision log.
		"""
		if row.attribute in KNOWN_VARIABLES:
			return

		frappe.throw(
			_(
				"Row {0}: {1} is not a variable the engine produces, so this band could never score. Use one of: {2}."
			).format(row.idx, row.attribute, ", ".join(KNOWN_VARIABLES))
		)

	def bands_by_attribute(self):
		grouped = {}

		for row in self.attributes:
			grouped.setdefault(row.attribute, []).append(row)

		return grouped


def validate_ranges(rows, low_field, high_field, label):
	reject_inverted(rows, low_field, high_field)
	reject_overlap(rows, low_field, high_field, label)


def reject_inverted(rows, low_field, high_field):
	for row in rows:
		if flt(row.get(low_field)) > flt(row.get(high_field)):
			frappe.throw(
				_("Row {0}: {1} {2} is above {3} {4}.").format(
					row.idx,
					_(row.meta.get_label(low_field)),
					row.get(low_field),
					_(row.meta.get_label(high_field)),
					row.get(high_field),
				)
			)


def reject_overlap(rows, low_field, high_field, label):
	ordered = sorted(rows, key=lambda row: flt(row.get(low_field)))

	for previous, current in pairwise(ordered):
		if flt(current.get(low_field)) <= flt(previous.get(high_field)):
			frappe.throw(
				_(
					"Rows {0} and {1} of {2} overlap. A value inside the overlap would score differently depending on row order."
				).format(previous.idx, current.idx, label)
			)
