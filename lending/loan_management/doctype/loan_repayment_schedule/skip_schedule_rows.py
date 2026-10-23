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

	def copy_history_rows(self):
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
		dates.update(self.get_carried_skipped_dates())
		return dates

	def get_carried_skipped_dates(self):
		if not self.previous:
			return set()

		resume_date = getdate(self.schedule.repayment_start_date)
		return {
			getdate(row.payment_date)
			for row in self.previous.repayment_schedule
			if row.demand_generated and not row.total_payment and getdate(row.payment_date) >= resume_date
		}
