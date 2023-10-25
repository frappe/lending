# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)


class LoanSecurityAssignment(Document):
	def validate(self):
		self.validate_securities()
		self.validate_loan_security_type()
		self.set_loan_and_security_values()

	def on_submit(self):
		if self.get("allocated_loans"):
			self.db_set("status", "Pledged")
			self.db_set("pledge_time", now_datetime())
			for d in self.get("allocated_loans"):
				update_shortfall_status(d.loan, self.total_security_value)
				update_loan(d.loan, self.maximum_loan_value)

	def on_update_after_submit(self):
		self.check_loan_securities_capability_to_book_additional_loans()

	def on_cancel(self):
		if self.get("allocated_loans"):
			self.db_set("status", "Cancelled")
			self.db_set("pledge_time", None)
			for d in self.get("allocated_loans"):
				update_loan(d.loan, self.maximum_loan_value, cancel=1)

	def validate_securities(self):
		security_list = []
		for security in self.securities:
			if security.loan_security not in security_list:
				security_list.append(security.loan_security)
			else:
				frappe.throw(
					_("Loan Security {0} added multiple times").format(frappe.bold(security.loan_security))
				)

	def validate_loan_security_type(self):
		existing_lsa = ""

		for d in self.get("allocated_loans"):
			if d.loan:
				lsa = frappe.qb.DocType("Loan Security Assignment")
				lsald = frappe.qb.DocType("Loan Security Assignment Loan Detail")

				existing_lsa = (
					frappe.qb.from_(lsa)
					.inner_join(lsald)
					.on(lsald.parent == lsa.name)
					.select(lsa.name)
					.where(lsa.docstatus == 1)
					.where(lsald.loan == d.loan)
				).run()

				break

		if existing_lsa:
			loan_security_type = frappe.db.get_value(
				"Pledge", {"parent": existing_lsa[0][0]}, ["loan_security_type"]
			)
		else:
			loan_security_type = self.securities[0].loan_security_type

		ltv_ratio_map = frappe._dict(
			frappe.get_all("Loan Security Type", fields=["name", "loan_to_value_ratio"], as_list=1)
		)

		ltv_ratio = ltv_ratio_map.get(loan_security_type)

		for security in self.securities:
			if ltv_ratio_map.get(security.loan_security_type) != ltv_ratio:
				frappe.throw(_("Loan Securities with different LTV ratio cannot be pledged against one loan"))

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

			pledge.amount = pledge.qty * pledge.loan_security_price
			pledge.post_haircut_amount = cint(pledge.amount - (pledge.amount * pledge.haircut / 100))

			total_security_value += pledge.amount
			maximum_loan_value += pledge.post_haircut_amount

		self.total_security_value = total_security_value
		self.maximum_loan_value = maximum_loan_value

		self.available_security_value = self.total_security_value

	def check_loan_securities_capability_to_book_additional_loans(self):
		total_security_value_needed = 0

		for d in self.get("allocated_loans"):
			loan_amount, status = frappe.db.get_value("Loan", d.loan, ["loan_amount", "status"])

			if status != "Sanctioned":
				continue

			total_security_value_needed += loan_amount

		if total_security_value_needed > self.available_security_value:
			frappe.throw(
				_("Loan Securities worth {0} needed more to book the loan").format(
					frappe.bold(flt(total_security_value_needed - self.available_security_value, 2)),
				)
			)

		for d in self.get("allocated_loans"):
			update_loan(d.loan, self.available_security_value)


def update_loan(loan, maximum_value_against_pledge, cancel=0):
	maximum_loan_value = frappe.db.get_value("Loan", {"name": loan}, ["maximum_loan_amount"])

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

	utilized_value_increased = (
		True
		if (trigger_doctype == "Loan Disbursement" and not on_trigger_doc_cancel)
		or (trigger_doctype == "Loan Repayment" and on_trigger_doc_cancel)
		else False
	)

	sorted_loan_security_assignments = _get_sorted_loan_security_assignments(
		loan, utilized_value_increased
	)

	_update_loan_securities_values(
		sorted_loan_security_assignments,
		amount,
		utilized_value_increased,
	)


def _get_sorted_loan_security_assignments(loan, utilized_value_increased):
	loan_security_assignments_w_ratio = []

	lsa = frappe.qb.DocType("Loan Security Assignment")
	lsald = frappe.qb.DocType("Loan Security Assignment Loan Detail")

	loan_security_assignments = (
		frappe.qb.from_(lsa)
		.inner_join(lsald)
		.on(lsald.parent == lsa.name)
		.select(
			lsa.name,
			lsa.total_security_value,
			lsa.utilized_security_value,
			lsa.available_security_value,
		)
		.where(lsa.status == "Pledged")
		.where(lsald.loan == loan)
	).run(as_dict=True)

	for loan_security_assignment in loan_security_assignments:
		utilized_to_original_value_ratio = flt(
			loan_security_assignment.utilized_security_value / loan_security_assignment.total_security_value
		)

		loan_security_assignments_w_ratio.append(
			frappe._dict(
				{
					"name": loan_security_assignment.name,
					"total_security_value": loan_security_assignment.total_security_value,
					"utilized_security_value": loan_security_assignment.utilized_security_value,
					"available_security_value": loan_security_assignment.available_security_value,
					"ratio": utilized_to_original_value_ratio,
				}
			)
		)

	sorted_loan_security_assignments = sorted(
		loan_security_assignments_w_ratio,
		key=lambda k: k["ratio"],
		reverse=utilized_value_increased,
	)

	return sorted_loan_security_assignments


def _update_loan_securities_values(
	sorted_loan_security_assignments,
	amount,
	utilized_value_increased,
):
	for loan_security_assignment in sorted_loan_security_assignments:
		if amount <= 0:
			break

		if utilized_value_increased:
			if (
				loan_security_assignment.utilized_security_value + amount
				> loan_security_assignment.total_security_value
			):
				new_utilized_security_value = loan_security_assignment.total_security_value
				new_available_security_value = 0
				amount = (
					amount
					+ loan_security_assignment.utilized_security_value
					- loan_security_assignment.total_security_value
				)
			else:
				new_utilized_security_value = loan_security_assignment.utilized_security_value + amount
				new_available_security_value = loan_security_assignment.available_security_value - amount
				amount = 0
		else:
			if (
				loan_security_assignment.available_security_value + amount
				> loan_security_assignment.total_security_value
			):
				new_available_security_value = loan_security_assignment.total_security_value
				new_utilized_security_value = 0
				amount = (
					amount
					+ loan_security_assignment.available_security_value
					- loan_security_assignment.total_security_value
				)
			else:
				new_utilized_security_value = loan_security_assignment.utilized_security_value - amount
				new_available_security_value = loan_security_assignment.available_security_value + amount
				amount = 0

		frappe.db.set_value(
			"Loan Security Assignment",
			loan_security_assignment.name,
			{
				"utilized_security_value": new_utilized_security_value,
				"available_security_value": new_available_security_value,
			},
		)
