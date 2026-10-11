# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import functions as fn
from frappe.utils import cint, comma_and, flt, now_datetime

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
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
		release_time: DF.Datetime | None
		securities: DF.Table[Pledge]
		status: DF.Literal["Pledge Requested", "Unpledged", "Pledged", "Release Requested", "Released", "Repossessed", "Cancelled"]
		total_security_value: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.validate_securities()
		self.set_loan_and_security_values()
		self.validate_security_limits()

	def before_submit(self):
		# With a loan application the pledge stays Pledge Requested until the loan is created,
		# so Loan.link_loan_security_assignment runs this check instead.
		if not self.loan_application:
			validate_lien_references(self.securities)

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
			frappe.throw(_("Loan Security {0} is disabled.").format(comma_and(disabled)))

	def validate_security_limits(self):
		limits = {
			d.name: d
			for d in frappe.get_all(
				"Loan Security Type",
				filters={"name": ("in", {row.loan_security_type for row in self.securities})},
				fields=["name", "max_single_security_pct", "max_exposure_per_security"],
			)
		}

		capped = [
			row.loan_security
			for row in self.securities
			if flt(limits.get(row.loan_security_type, {}).get("max_exposure_per_security"))
		]
		pledged_qty = get_pledged_qty(capped) if capped else {}

		for row in self.securities:
			limit = limits.get(row.loan_security_type)
			if not limit:
				continue

			share = flt(row.amount) / flt(self.total_security_value) * 100 if self.total_security_value else 0
			if flt(limit.max_single_security_pct) and flt(share, 2) > flt(limit.max_single_security_pct):
				frappe.throw(
					_("Row {0}: {1} is {2}% of this pledge. Loan Security Type {3} allows at most {4}%.").format(
						row.idx,
						frappe.bold(row.loan_security),
						flt(share, 2),
						frappe.bold(row.loan_security_type),
						flt(limit.max_single_security_pct),
					),
					title=_("Pledge Too Concentrated"),
				)

			if flt(limit.max_exposure_per_security):
				exposure = (flt(pledged_qty.get(row.loan_security)) + flt(row.qty)) * flt(row.loan_security_price)
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


def validate_lien_references(securities):
	missing = [row.get("loan_security") for row in securities if not (row.get("lien_reference") or "").strip()]

	if missing:
		frappe.throw(
			_("Add the lien reference for {0} before the pledge is marked Pledged.").format(
				comma_and(missing)
			),
			title=_("Lien Reference Missing"),
		)


def get_pledged_qty(securities):
	# Pledge Requested counts too: it becomes Pledged without passing validate again.
	lsa = frappe.qb.DocType("Loan Security Assignment")
	pledge = frappe.qb.DocType("Pledge")
	release = frappe.qb.DocType("Loan Security Release")
	unpledge = frappe.qb.DocType("Unpledge")

	pledged = frappe._dict(
		frappe.qb.from_(pledge)
		.inner_join(lsa)
		.on(pledge.parent == lsa.name)
		.select(pledge.loan_security, fn.Sum(pledge.qty))
		.where(lsa.docstatus == 1)
		.where(lsa.status.isin(["Pledge Requested", "Pledged"]))
		.where(pledge.loan_security.isin(securities))
		.groupby(pledge.loan_security)
		.run()
	)
	released = frappe._dict(
		frappe.qb.from_(unpledge)
		.inner_join(release)
		.on(unpledge.parent == release.name)
		.select(unpledge.loan_security, fn.Sum(unpledge.qty))
		.where(release.docstatus == 1)
		.where(release.status == "Approved")
		.where(unpledge.loan_security.isin(securities))
		.groupby(unpledge.loan_security)
		.run()
	)

	return {security: flt(qty) - flt(released.get(security)) for security, qty in pledged.items()}


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
def release_loan_security_assignment(loan_security_assignment: str):
	frappe.has_permission("Loan Security Assignment", "write", doc=loan_security_assignment, throw=True)

	frappe.db.set_value(
		"Loan Security Assignment",
		loan_security_assignment,
		{"status": "Released", "release_time": now_datetime()},
	)
