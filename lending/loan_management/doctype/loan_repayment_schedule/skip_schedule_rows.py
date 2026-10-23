# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import getdate


class SkipScheduleRows:
	"""Rows an "Installment Skip" schedule takes over from the schedule it replaces.

	Like Pre Payment and Advance Payment schedules, it keeps every earlier row, so the Active
	schedule always shows the whole loan. Earlier skips stay skipped when a later one is added.
	"""

	def __init__(self, schedule):
		self.schedule = schedule
		self.previous = self.get_previous_schedule()

	def get_previous_schedule(self):
		filters = {
			"loan": self.schedule.loan,
			"docstatus": 1,
			"status": "Active",
			"name": ("!=", self.schedule.name or ""),
		}
		if self.schedule.loan_disbursement:
			filters["loan_disbursement"] = self.schedule.loan_disbursement

		name = frappe.db.get_value("Loan Repayment Schedule", filters, "name")
		return frappe.get_doc("Loan Repayment Schedule", name) if name else None

	def get_resume_date(self):
		return frappe.db.get_value("Loan Restructure", self.schedule.loan_restructure, "repayment_start_date")

	def get_original_start_date(self):
		return self.previous.repayment_start_date if self.previous else self.schedule.repayment_start_date

	def copy_completed_rows(self):
		if not self.previous:
			return

		resume_date = getdate(self.schedule.repayment_start_date)
		for row in self.previous.repayment_schedule:
			if getdate(row.payment_date) >= resume_date:
				continue

			self.schedule.add_repayment_schedule_row(
				row.payment_date,
				row.principal_amount,
				row.interest_amount,
				row.charges,
				row.total_payment,
				row.balance_loan_amount,
				row.number_of_days,
				demand_generated=row.demand_generated,
			)

	def get_skipped_dates(self):
		"""Dates skipped by this restructure and by earlier skips that are still ahead"""
		dates = {
			getdate(date)
			for date in frappe.get_all(
				"Loan Skipped Installment", {"parent": self.schedule.loan_restructure}, pluck="payment_date"
			)
		}
		dates.update(self.get_earlier_skipped_dates())
		return dates

	def get_earlier_skipped_dates(self):
		resume_date = getdate(self.schedule.repayment_start_date)
		dates = get_approved_skipped_dates(self.schedule.loan, self.schedule.loan_restructure)
		return {date for date in dates if date >= resume_date}


def get_approved_skipped_dates(loan, exclude_restructure=None):
	"""Dates skipped by approved Installment Skips. Read from the skips, not the schedule rows:
	a skipped date at the end of the term has no row."""
	Restructure = frappe.qb.DocType("Loan Restructure")
	Skipped = frappe.qb.DocType("Loan Skipped Installment")

	query = (
		frappe.qb.from_(Skipped)
		.join(Restructure)
		.on(Skipped.parent == Restructure.name)
		.select(Skipped.payment_date)
		.where(
			(Restructure.loan == loan)
			& (Restructure.docstatus == 1)
			& (Restructure.status == "Approved")
			& (Restructure.restructure_type == "Installment Skip")
		)
	)
	if exclude_restructure:
		query = query.where(Restructure.name != exclude_restructure)

	return {getdate(date) for date in query.run(pluck=True)}
