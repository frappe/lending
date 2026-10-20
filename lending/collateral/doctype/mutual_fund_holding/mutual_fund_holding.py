# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import functions as fn
from frappe.utils import flt

JOINT_HOLDINGS = ("Joint", "Anyone or Survivor")
# Statuses whose units are still under lien. Partial releases are not netted until Unpledge names the holding
OPEN_ASSIGNMENT_STATUSES = ("Pledge Requested", "Pledged", "Release Requested")


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
		self.validate_scheme()
		self.validate_holding_type()
		self.validate_duplicate()
		self.validate_units_held()
		self.set_applicant_name()
		self.title = f"{self.folio_number} - {self.loan_security}"

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

	def validate_units_held(self):
		if self.units_held and not self.is_new() and self.pledged_units > flt(self.units_held):
			frappe.throw(
				_("Units Held cannot be less than the {0} units pledged from this folio").format(
					frappe.bold(self.pledged_units)
				)
			)

	def set_applicant_name(self):
		if self.applicant_type == "Customer":
			self.applicant_name = frappe.db.get_value("Customer", self.applicant, "customer_name")
		elif self.applicant_type == "Employee":
			self.applicant_name = frappe.db.get_value("Employee", self.applicant, "employee_name")


def get_pledged_units(holding, exclude_assignment=None):
	"""Units of the holding on submitted pledges that are still open."""
	pledge = frappe.qb.DocType("Pledge")
	assignment = frappe.qb.DocType("Loan Security Assignment")
	query = (
		frappe.qb.from_(pledge)
		.inner_join(assignment)
		.on(pledge.parent == assignment.name)
		.select(fn.Sum(pledge.qty))
		.where(pledge.parenttype == "Loan Security Assignment")
		.where(pledge.mutual_fund_holding == holding)
		.where(assignment.docstatus == 1)
		.where(assignment.status.isin(OPEN_ASSIGNMENT_STATUSES))
	)
	if exclude_assignment:
		query = query.where(assignment.name != exclude_assignment)
	return flt(query.run()[0][0])
