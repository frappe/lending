# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import functions as fn
from frappe.utils import flt

JOINT_HOLDINGS = ("Joint", "Anyone or Survivor")
# A Repossessed assignment stays counted so that the sales which emptied it net it out
OPEN_ASSIGNMENT_STATUSES = ("Pledge Requested", "Pledged", "Release Requested", "Repossessed")
FIXED_ONCE_PLEDGED = ("applicant_type", "applicant", "loan_security", "folio_number")


class MutualFundHolding(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.collateral.doctype.mutual_fund_holding_lot.mutual_fund_holding_lot import (
			MutualFundHoldingLot,
		)

		all_holders_signed: DF.Check
		amfi_scheme_code: DF.Data | None
		applicant: DF.DynamicLink
		applicant_name: DF.Data | None
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		fetched_on: DF.Datetime | None
		folio_number: DF.Data
		holding_mode: DF.Literal["", "Demat", "Statement of Account"]
		holding_type: DF.Literal["", "Single", "Joint", "Anyone or Survivor", "Minor"]
		loan_security: DF.Link
		lock_in_days: DF.Int
		lots: DF.Table[MutualFundHoldingLot]
		rta: DF.Data | None
		statement: DF.Attach | None
		title: DF.Data | None
		units_held: DF.Float
	# end: auto-generated types

	@property
	def pledged_units(self):
		return get_pledged_units(self.name) if not self.is_new() else 0

	@property
	def status(self):
		pledged_units = self.pledged_units
		if not pledged_units:
			return "Free"
		if self.units_held and pledged_units < self.units_held:
			return "Partly Pledged"
		return "Pledged"

	def validate(self):
		self.folio_number = (self.folio_number or "").strip()
		if not self.is_new():
			# The same lock a pledge takes, so a pledge cannot land between this read and the save
			frappe.db.get_value("Mutual Fund Holding", self.name, "name", for_update=True)
		pledged_units = self.pledged_units
		self.validate_fixed_once_pledged(pledged_units)
		self.validate_scheme()
		self.validate_holding_type()
		self.validate_duplicate()
		self.validate_units_held(pledged_units)
		self.set_applicant_name()
		self.title = f"{self.folio_number} - {self.loan_security}"

	def validate_fixed_once_pledged(self, pledged_units):
		if not pledged_units:
			return
		for fieldname in FIXED_ONCE_PLEDGED:
			if self.has_value_changed(fieldname):
				frappe.throw(
					_("{0} cannot be changed while units of this folio are pledged").format(
						frappe.bold(_(self.meta.get_label(fieldname)))
					)
				)

	def validate_scheme(self):
		if not frappe.db.get_value("Loan Security", self.loan_security, "is_mutual_fund"):
			frappe.throw(_("Loan Security {0} is not a mutual fund scheme").format(frappe.bold(self.loan_security)))

	def validate_holding_type(self):
		if self.holding_type == "Minor":
			frappe.throw(_("Units in a minor's folio cannot be pledged"))
		if self.holding_type in JOINT_HOLDINGS and not self.all_holders_signed:
			frappe.throw(
				_(
					"Every holder of folio {0} must sign the lien. Tick All Holders Signed the Lien once they have"
				).format(frappe.bold(self.folio_number))
			)

	def validate_duplicate(self):
		existing = frappe.db.get_value(
			"Mutual Fund Holding",
			{
				"applicant_type": self.applicant_type,
				"applicant": self.applicant,
				"loan_security": self.loan_security,
				"folio_number": self.folio_number,
				"name": ("!=", self.name),
			},
		)
		if existing:
			frappe.throw(
				_("Folio {0} of {1} is already recorded as Mutual Fund Holding {2}").format(
					frappe.bold(self.folio_number), frappe.bold(self.loan_security), frappe.bold(existing)
				)
			)

	def validate_units_held(self, pledged_units):
		if self.units_held and pledged_units > flt(self.units_held):
			frappe.throw(
				_("Units Held cannot be less than the {0} units pledged from this folio").format(
					frappe.bold(pledged_units)
				)
			)

	def set_applicant_name(self):
		if self.applicant_type == "Customer":
			self.applicant_name = frappe.db.get_value("Customer", self.applicant, "customer_name")
		elif self.applicant_type == "Employee":
			self.applicant_name = frappe.db.get_value("Employee", self.applicant, "employee_name")


def on_doctype_update():
	# Two staff saving the same folio at once must not end up with two holdings and two caps
	frappe.db.add_unique(
		"Mutual Fund Holding",
		["applicant_type", "applicant", "loan_security", "folio_number"],
		constraint_name="unique_folio_per_applicant_and_scheme",
	)


def get_pledged_units(holding, exclude_assignment=None):
	"""Units of the holding on submitted pledges that are still open, less what was released or sold.

	Releases and sales name the loan (or, without a loan, the applicant) and the scheme, not the folio.
	They are netted where this holding is the only folio of its scheme. Elsewhere the units stay
	counted in full. The lines of an excluded assignment are left out before netting.
	"""
	holding_doc = frappe.db.get_value(
		"Mutual Fund Holding", holding, ["loan_security", "applicant_type", "applicant"], as_dict=True
	)
	if not holding_doc:
		return 0
	loan_security = holding_doc.loan_security
	no_loan = (holding_doc.applicant_type, holding_doc.applicant)

	pledge = frappe.qb.DocType("Pledge")
	assignment = frappe.qb.DocType("Loan Security Assignment")
	lines = (
		frappe.qb.from_(pledge)
		.inner_join(assignment)
		.on(pledge.parent == assignment.name)
		.select(
			assignment.name,
			assignment.loan,
			assignment.applicant_type,
			assignment.applicant,
			pledge.mutual_fund_holding,
			fn.Sum(pledge.qty),
		)
		.where(pledge.parenttype == "Loan Security Assignment")
		.where(pledge.loan_security == loan_security)
		.where(assignment.docstatus == 1)
		.where(assignment.status.isin(OPEN_ASSIGNMENT_STATUSES))
		.groupby(
			assignment.name,
			assignment.loan,
			assignment.applicant_type,
			assignment.applicant,
			pledge.mutual_fund_holding,
		)
	).run()

	holding_qty, scheme_qty, excluded_qty = defaultdict(float), defaultdict(float), defaultdict(float)
	applicant_scheme_qty = applicant_holding_qty = 0
	for assignment_name, loan, applicant_type, applicant, line_holding, qty in lines:
		# Pledges without a loan are released per applicant
		bucket = loan or (applicant_type, applicant)
		scheme_qty[bucket] += flt(qty)
		if (applicant_type, applicant) == no_loan:
			applicant_scheme_qty += flt(qty)
		if line_holding == holding:
			holding_qty[bucket] += flt(qty)
			applicant_holding_qty += flt(qty)
			if assignment_name == exclude_assignment:
				excluded_qty[bucket] += flt(qty)

	sole_folio = [bucket for bucket, qty in holding_qty.items() if qty == scheme_qty[bucket]]
	# A release without a loan is checked against all the applicant's pledges, loan or not, so its
	# units belong to this folio only when no other folio of the scheme is pledged by the applicant
	no_loan_sole_folio = no_loan in holding_qty and applicant_holding_qty == applicant_scheme_qty
	taken_out = get_released_and_sold_qty(
		loan_security,
		[bucket for bucket in sole_folio if bucket != no_loan],
		no_loan if no_loan_sole_folio else None,
	)

	return sum(
		max(qty - excluded_qty[bucket] - taken_out.get(bucket, 0), 0) for bucket, qty in holding_qty.items()
	)


def get_released_and_sold_qty(loan_security, loans, no_loan_applicant=None):
	"""Units of the scheme released or sold, per loan, and per applicant for releases without a loan."""
	taken_out = defaultdict(float)
	if no_loan_applicant:
		unpledge = frappe.qb.DocType("Unpledge")
		release = frappe.qb.DocType("Loan Security Release")
		applicant_type, applicant = no_loan_applicant
		released = (
			frappe.qb.from_(unpledge)
			.inner_join(release)
			.on(unpledge.parent == release.name)
			.select(fn.Sum(unpledge.qty))
			.where(unpledge.loan_security == loan_security)
			.where(release.docstatus == 1)
			.where(release.status == "Approved")
			.where(release.applicant_type == applicant_type)
			.where(release.applicant == applicant)
			.where(release.loan.isnull() | (release.loan == ""))
		).run()
		taken_out[no_loan_applicant] += flt(released[0][0])

	if not loans:
		return taken_out

	unpledge = frappe.qb.DocType("Unpledge")
	release = frappe.qb.DocType("Loan Security Release")
	released = (
		frappe.qb.from_(unpledge)
		.inner_join(release)
		.on(unpledge.parent == release.name)
		.select(release.loan, fn.Sum(unpledge.qty))
		.where(unpledge.loan_security == loan_security)
		.where(release.docstatus == 1)
		.where(release.status == "Approved")
		.where(release.loan.isin(loans))
		.groupby(release.loan)
	).run()

	item = frappe.qb.DocType("Loan Security Sale Item")
	sale = frappe.qb.DocType("Loan Security Sale")
	sold = (
		frappe.qb.from_(item)
		.inner_join(sale)
		.on(item.parent == sale.name)
		.select(sale.loan, fn.Sum(item.sold_qty))
		.where(item.loan_security == loan_security)
		.where(sale.docstatus == 1)
		.where(sale.loan.isin(loans))
		.groupby(sale.loan)
	).run()

	for loan, qty in (*released, *sold):
		taken_out[loan] += flt(qty)
	return taken_out
