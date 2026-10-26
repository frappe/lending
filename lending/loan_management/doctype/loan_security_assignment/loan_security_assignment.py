# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, comma_and, flt, now_datetime

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
	get_loan_security_price_map,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_qty_map,
	update_sanctioned_loan_amount_for_applicant,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)


class LoanSecurityAssignment(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.pledge.pledge import Pledge

		amended_from: DF.Link | None
		applicant: DF.DynamicLink
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		company: DF.Link
		description: DF.Text | None
		loan: DF.Link | None
		loan_application: DF.Link | None
		maximum_loan_value: DF.Currency
		pledge_time: DF.Datetime | None
		reference_no: DF.Data | None
		release_reference: DF.Data | None
		release_time: DF.Datetime | None
		securities: DF.Table[Pledge]
		status: DF.Literal["Pledge Requested", "Unpledged", "Pledged", "Release Requested", "Released", "Repossessed", "Cancelled"]
		total_security_value: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.validate_securities()
		self.set_loan_and_security_values()
		self.validate_security_limits()

	def on_submit(self):
		if self.loan:
			update_shortfall_status(self.loan, self.total_security_value)
			update_loan(self.loan, self.maximum_loan_value)

		if not self.loan_application:
			self.db_set("status", "Pledged")
			self.db_set("pledge_time", now_datetime())

			# Create Sanctioned Loan Amount Record
			current_sanctioned_amount = frappe.db.get_value(
				"Sanctioned Loan Amount",
				{"applicant": self.applicant, "applicant_type": self.applicant_type},
				"name",
			)

			if not current_sanctioned_amount:
				frappe.get_doc({
					"doctype": "Sanctioned Loan Amount",
					"applicant": self.applicant,
					"applicant_type": self.applicant_type,
					"company": self.company,
					"sanctioned_amount_limit": self.maximum_loan_value
				}).insert()
			else:
				update_sanctioned_loan_amount_for_applicant(self.applicant, self.applicant_type)

	def on_update_after_submit(self):
		self.check_loan_securities_capability_to_book_additional_loans()

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		self.db_set("pledge_time", None)
		if self.loan:
			update_loan(self.loan, self.maximum_loan_value, cancel=1)
		update_sanctioned_loan_amount_for_applicant(self.applicant, self.applicant_type)

	def validate_securities(self):
		if not self.get("securities"):
			frappe.throw(_("Atlest one security needs to be assigned"))

		security_list = []
		for security in self.get("securities"):
			if security.loan_security not in security_list:
				security_list.append(security.loan_security)
			else:
				frappe.throw(
					_("Loan Security {0} added multiple times").format(frappe.bold(security.loan_security))
				)

		disabled = frappe.get_all(
			"Loan Security", filters={"name": ("in", security_list), "disabled": 1}, pluck="name"
		)
		if disabled:
			frappe.throw(
				_("Loan Security {0} is disabled.").format(comma_and(disabled)),
				title=_("Loan Security Disabled"),
			)

	def validate_security_limits(self):
		limits = {
			d.name: d
			for d in frappe.get_all(
				"Loan Security Type",
				filters={"name": ("in", {row.loan_security_type for row in self.securities})},
				fields=["name", "max_single_security_pct", "max_exposure_per_security"],
			)
		}

		if not any(
			flt(limit.max_single_security_pct) or flt(limit.max_exposure_per_security) for limit in limits.values()
		):
			return

		if self.loan:
			# Locks are taken Loan, then Loan Security, then pledge and release rows. A Loan Security
			# Release locks its Loan before its own row (see LoanSecurityRelease.save), so the two
			# cannot deadlock.
			lock_loan(self.loan)

		capped = sorted(
			{
				row.loan_security
				for row in self.securities
				if flt(limits.get(row.loan_security_type, {}).get("max_exposure_per_security"))
			}
		)
		pledged_qty, current_prices = {}, {}
		if capped:
			lock_loan_securities(capped)
			pledged_qty = get_pledged_qty_map(securities=capped, for_update=True)
			# A row from a loan application keeps the price from when it was applied for.
			current_prices = get_loan_security_price_map(capped)

		shares = {}
		if any(flt(limit.max_single_security_pct) for limit in limits.values()):
			shares = self.get_security_shares()

		for row in self.securities:
			limit = limits.get(row.loan_security_type)
			if not limit:
				continue

			share = flt(shares.get(row.loan_security), 2)
			if flt(limit.max_single_security_pct) and share > flt(limit.max_single_security_pct):
				if self.loan:
					msg = _(
						"Row {0}: {1} would be {2}% of the collateral on Loan {3}. Loan Security Type {4} allows at most {5}%."
					).format(
						row.idx,
						frappe.bold(row.loan_security),
						share,
						frappe.bold(self.loan),
						frappe.bold(row.loan_security_type),
						flt(limit.max_single_security_pct),
					)
				else:
					msg = _(
						"Row {0}: {1} is {2}% of this pledge. Loan Security Type {3} allows at most {4}%."
					).format(
						row.idx,
						frappe.bold(row.loan_security),
						share,
						frappe.bold(row.loan_security_type),
						flt(limit.max_single_security_pct),
					)
				frappe.throw(msg, title=_("Pledge Too Concentrated"))

			if flt(limit.max_exposure_per_security):
				price = flt(current_prices.get(row.loan_security)) or flt(row.loan_security_price)
				exposure = (flt(pledged_qty.get(row.loan_security)) + flt(row.qty)) * price
				if exposure > flt(limit.max_exposure_per_security):
					frappe.throw(
						_(
							"Row {0}: {1} pledged across all borrowers would be worth {2}. Loan Security Type {3} allows at most {4}."
						).format(
							row.idx,
							frappe.bold(row.loan_security),
							frappe.format_value(exposure, {"fieldtype": "Currency"}),
							frappe.bold(row.loan_security_type),
							frappe.format_value(limit.max_exposure_per_security, {"fieldtype": "Currency"}),
						),
						title=_("Exposure Limit Reached"),
					)

	def get_security_shares(self):
		# A top-up adds to the collateral already on the loan, so the share is measured across both,
		# all at the current price.
		quantities = {}
		for row in self.securities:
			quantities[row.loan_security] = quantities.get(row.loan_security, 0) + flt(row.qty)

		if self.loan:
			# The Loan is locked in validate_security_limits, so concurrent top-ups are checked in turn.
			for security, qty in get_pledged_qty_map(loan=self.loan, for_update=True).items():
				quantities[security] = quantities.get(security, 0) + flt(qty)

		current_prices = get_loan_security_price_map(list(quantities))
		saved_prices = {row.loan_security: flt(row.loan_security_price) for row in self.securities}
		if self.loan:
			# A security already on the loan whose price has expired keeps the price it was pledged at,
			# so it still counts toward the total.
			for security, price in self.get_loan_pledge_prices().items():
				saved_prices.setdefault(security, price)

		values = {
			security: qty * (flt(current_prices.get(security)) or saved_prices.get(security, 0))
			for security, qty in quantities.items()
		}

		total = sum(values.values())
		return {security: value / total * 100 for security, value in values.items()} if total else {}

	def get_loan_pledge_prices(self):
		pledge = frappe.qb.DocType("Pledge")
		lsa = frappe.qb.DocType("Loan Security Assignment")
		rows = (
			frappe.qb.from_(pledge)
			.inner_join(lsa)
			.on(pledge.parent == lsa.name)
			.select(pledge.loan_security, pledge.loan_security_price)
			.where(lsa.loan == self.loan)
			.where(lsa.docstatus == 1)
			.where(lsa.status == "Pledged")
			.orderby(lsa.pledge_time)
		).run()
		# The latest pledge of each security wins.
		return {security: flt(price) for security, price in rows}

	def set_loan_and_security_values(self):
		total_security_value = 0
		maximum_loan_value = 0

		for pledge in self.securities:
			if not pledge.qty:
				frappe.throw(_("Qty is mandatory for loan security!"))

			if not pledge.loan_security_price:
				loan_security_price = get_loan_security_price(pledge.loan_security)

				if loan_security_price:
					pledge.loan_security_price = loan_security_price
				else:
					frappe.throw(
						_("No valid Loan Security Price found for {0}").format(frappe.bold(pledge.loan_security))
					)

			haircut = pledge.haircut

			if not haircut:
				haircut = flt(frappe.db.get_value("Loan Security Type", pledge.loan_security_type, "haircut"))

			pledge.amount = pledge.qty * pledge.loan_security_price
			pledge.post_haircut_amount = cint(pledge.amount - (pledge.amount * haircut / 100))

			total_security_value += pledge.amount
			maximum_loan_value += pledge.post_haircut_amount

		self.total_security_value = total_security_value
		self.maximum_loan_value = maximum_loan_value

	def check_loan_securities_capability_to_book_additional_loans(self):
		if not self.loan:
			return

		loan_amount, status = frappe.db.get_value("Loan", self.loan, ["loan_amount", "status"])

		if status != "Sanctioned":
			return

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		total_security_value_needed = flt(loan_amount, precision)

		total_available_security_value = 0
		for d in self.get("securities"):
			total_available_security_value += flt(
				frappe.db.get_value("Loan Security", d.loan_security, "available_security_value"), precision
			)

		if total_security_value_needed > total_available_security_value:
			frappe.throw(
				_("Loan Securities worth {0} needed more to book the loan").format(
					frappe.bold(flt(total_security_value_needed - total_available_security_value, precision)),
				)
			)

		update_loan(self.loan, total_available_security_value)


def lock_loan(loan):
	frappe.db.get_value("Loan", loan, "name", for_update=True)


def lock_loan_securities(securities):
	# Serialises concurrent pledges of the same security, so two cannot both pass the exposure cap.
	ls = frappe.qb.DocType("Loan Security")
	frappe.qb.from_(ls).select(ls.name).where(ls.name.isin(securities)).orderby(ls.name).for_update().run()


def update_loan(loan, maximum_value_against_pledge, cancel=0):
	precision = cint(frappe.db.get_default("currency_precision")) or 2
	maximum_loan_value = flt(frappe.db.get_value("Loan", {"name": loan}, "maximum_loan_amount"), precision)
	maximum_value_against_pledge = flt(maximum_value_against_pledge, precision)

	if cancel:
		frappe.db.sql(
			""" UPDATE `tabLoan` SET maximum_loan_amount=%s
			WHERE name=%s""",
			(maximum_loan_value - maximum_value_against_pledge, loan),
		)
	else:
		frappe.db.sql(
			""" UPDATE `tabLoan` SET maximum_loan_amount=%s, is_secured_loan=1
			WHERE name=%s""",
			(maximum_loan_value + maximum_value_against_pledge, loan),
		)


def update_loan_securities_values(
	loan,
	amount,
	trigger_doctype,
	on_trigger_doc_cancel=0,
):
	if not frappe.db.get_value("Loan", loan, "is_secured_loan"):
		return

	precision = cint(frappe.db.get_default("currency_precision")) or 2

	utilized_value_increased = (
		True
		if (trigger_doctype == "Loan Disbursement" and not on_trigger_doc_cancel)
		or (trigger_doctype == "Loan Repayment" and on_trigger_doc_cancel)
		else False
	)

	ls = frappe.qb.DocType("Loan Security")
	lsa = frappe.qb.DocType("Loan Security Assignment")
	pledge = frappe.qb.DocType("Pledge")

	loan_securities = (
		frappe.qb.from_(lsa)
		.inner_join(pledge)
		.on(pledge.parent == lsa.name)
		.inner_join(ls)
		.on(pledge.loan_security == ls.name)
		.select(
			ls.name,
			ls.available_security_value,
			ls.utilized_security_value,
			ls.original_security_value,
		)
		.where(lsa.status == "Pledged")
		.where(lsa.loan == loan)
	).run(as_dict=True)

	for loan_security in loan_securities:
		if amount <= 0:
			break

		utilized_security_value = flt(loan_security.utilized_security_value, precision)
		available_security_value = flt(loan_security.available_security_value, precision)
		original_security_value = flt(loan_security.original_security_value, precision)

		if utilized_value_increased:
			if utilized_security_value + amount > original_security_value:
				new_utilized_security_value = original_security_value
				new_available_security_value = 0
				amount = amount + utilized_security_value - original_security_value
			else:
				new_utilized_security_value = utilized_security_value + amount
				new_available_security_value = available_security_value - amount
				amount = 0
		else:
			if available_security_value + amount > original_security_value:
				new_available_security_value = original_security_value
				new_utilized_security_value = 0
				amount = amount + available_security_value - original_security_value
			else:
				new_utilized_security_value = utilized_security_value - amount
				new_available_security_value = available_security_value + amount
				amount = 0

		frappe.db.set_value(
			"Loan Security",
			loan_security.name,
			{
				"utilized_security_value": new_utilized_security_value,
				"available_security_value": new_available_security_value,
			},
		)


@frappe.whitelist()
def release_loan_security_assignment(loan_security_assignment: str, release_reference: str | None = None):
	frappe.has_permission("Loan Security Assignment", "write", doc=loan_security_assignment, throw=True)

	frappe.db.set_value(
		"Loan Security Assignment",
		loan_security_assignment,
		{
			"status": "Released",
			"release_time": now_datetime(),
			"release_reference": (release_reference or "").strip() or None,
		},
	)
