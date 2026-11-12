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

		all_holders_signed: DF.Check
		amfi_scheme_code: DF.Data | None
		applicant: DF.DynamicLink
		applicant_name: DF.Data | None
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		folio_number: DF.Data
		holding_mode: DF.Literal["", "Demat", "Statement of Account"]
		holding_type: DF.Literal["", "Single", "Joint", "Anyone or Survivor", "Minor"]
		loan_security: DF.Link
		lock_in_days: DF.Int
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
		pledged_units = 0
		if not self.is_new():
			# The same lock a pledge takes, so a pledge cannot land between this read and the save
			frappe.db.get_value("Mutual Fund Holding", self.name, "name", for_update=True)
			pledged_units = get_pledged_units(self.name, for_update=True)
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


def get_pledged_units(holding, exclude_assignment=None, for_update=False):
	pledge = frappe.qb.DocType("Pledge")
	assignment = frappe.qb.DocType("Loan Security Assignment")
	query = (
		frappe.qb.from_(pledge)
		.inner_join(assignment)
		.on(pledge.parent == assignment.name)
		.select(
			assignment.name,
			assignment.loan,
			assignment.applicant_type,
			assignment.applicant,
			fn.Sum(pledge.qty),
		)
		.where(pledge.parenttype == "Loan Security Assignment")
		.where(pledge.mutual_fund_holding == holding)
		.where(assignment.docstatus == 1)
		.where(assignment.status.isin(OPEN_ASSIGNMENT_STATUSES))
		.groupby(assignment.name, assignment.loan, assignment.applicant_type, assignment.applicant)
	)
	# Only the pledges need the locking read: a stale count of releases and sales overstates the units
	lines = (query.for_update() if for_update else query).run()

	pledged, excluded = defaultdict(float), defaultdict(float)
	for assignment_name, loan, applicant_type, applicant, qty in lines:
		# Pledges without a loan are released per applicant
		bucket = loan or (applicant_type, applicant)
		pledged[bucket] += flt(qty)
		if assignment_name == exclude_assignment:
			excluded[bucket] += flt(qty)

	taken_out = get_released_and_sold_units(holding)
	return sum(max(qty - excluded[bucket] - taken_out[bucket], 0) for bucket, qty in pledged.items())


def get_released_and_sold_units(holding):
	unpledge = frappe.qb.DocType("Unpledge")
	release = frappe.qb.DocType("Loan Security Release")
	released = (
		frappe.qb.from_(unpledge)
		.inner_join(release)
		.on(unpledge.parent == release.name)
		.select(release.loan, release.applicant_type, release.applicant, fn.Sum(unpledge.qty))
		.where(unpledge.mutual_fund_holding == holding)
		.where(release.docstatus == 1)
		.where(release.status == "Approved")
		.groupby(release.loan, release.applicant_type, release.applicant)
	).run()

	item = frappe.qb.DocType("Loan Security Sale Item")
	sale = frappe.qb.DocType("Loan Security Sale")
	sold = (
		frappe.qb.from_(item)
		.inner_join(sale)
		.on(item.parent == sale.name)
		.select(sale.loan, sale.applicant_type, sale.applicant, fn.Sum(item.sold_qty))
		.where(item.mutual_fund_holding == holding)
		.where(sale.docstatus == 1)
		.groupby(sale.loan, sale.applicant_type, sale.applicant)
	).run()

	taken_out = defaultdict(float)
	for loan, applicant_type, applicant, qty in (*released, *sold):
		taken_out[loan or (applicant_type, applicant)] += flt(qty)
	return taken_out
