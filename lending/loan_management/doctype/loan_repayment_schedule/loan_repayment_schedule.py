# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, cint, date_diff, flt, get_last_day, getdate


class LoanRepaymentSchedule(Document):
	def validate(self):
		self.validate_repayment_method()
		self.set_missing_fields()
		self.make_repayment_schedule()
		self.set_repayment_period()

	def set_missing_fields(self):
		if self.repayment_method == "Repay Over Number of Periods":
			self.monthly_repayment_amount = get_monthly_repayment_amount(
				self.disbursed_amount or self.loan_amount,
				self.rate_of_interest,
				self.repayment_periods,
				self.repayment_frequency,
			)

	def set_repayment_period(self):
		if self.repayment_method == "Repay Fixed Amount per Period":
			repayment_periods = len(self.repayment_schedule)

			self.repayment_periods = repayment_periods

	def make_repayment_schedule(self):
		if not self.repayment_start_date:
			frappe.throw(_("Repayment Start Date is mandatory for term loans"))

		self.repayment_schedule = []
		payment_date = self.repayment_start_date
		balance_amount = self.disbursed_amount or self.loan_amount
		carry_forward_interest = self.adjusted_interest
		moratorium_interest = 0

		if self.moratorium_tenure and self.repayment_frequency == "Monthly":
			payment_date = add_months(self.repayment_start_date, -1 * self.moratorium_tenure)
			moratorium_end_date = add_months(self.repayment_start_date, -1)

		tenure = self.repayment_periods
		if self.repayment_frequency == "Monthly":
			tenure += cint(self.moratorium_tenure)

		broken_period_interest_days = date_diff(add_months(payment_date, -1), self.posting_date)
		if broken_period_interest_days > 0:
			tenure += 1

		self.add_rows_from_prev_disbursement()
		if len(self.get("repayment_schedule")) > 0:
			broken_period_interest_days = 0

		while balance_amount > 0:
			if (
				self.moratorium_tenure
				and self.repayment_frequency == "Monthly"
				and getdate(payment_date) > getdate(moratorium_end_date)
			):
				if self.treatment_of_interest == "Capitalize" and moratorium_interest:
					balance_amount = self.loan_amount + moratorium_interest
					self.monthly_repayment_amount = get_monthly_repayment_amount(
						balance_amount, self.rate_of_interest, self.repayment_periods, self.repayment_frequency
					)
					moratorium_interest = 0

			interest_amount, principal_amount, balance_amount, total_payment, days = self.get_amounts(
				payment_date,
				balance_amount,
				broken_period_interest_days,
				carry_forward_interest,
			)

			if self.moratorium_tenure and self.repayment_frequency == "Monthly":
				if getdate(payment_date) <= getdate(moratorium_end_date):
					total_payment = 0
					balance_amount = self.loan_amount
					moratorium_interest += interest_amount
				elif self.treatment_of_interest == "Add to first repayment" and moratorium_interest:
					if moratorium_interest + interest_amount <= total_payment:
						interest_amount += moratorium_interest
						principal_amount = total_payment - interest_amount
						balance_amount = self.loan_amount - principal_amount
						moratorium_interest = 0

			if self.repayment_schedule_type == "Pro-rated calendar months":
				next_payment_date = get_last_day(payment_date)
				if self.repayment_date_on == "Start of the next month":
					next_payment_date = add_days(next_payment_date, 1)

				payment_date = next_payment_date

			self.add_repayment_schedule_row(
				payment_date, principal_amount, interest_amount, total_payment, balance_amount, days
			)

			if (
				self.repayment_method == "Repay Over Number of Periods"
				and self.repayment_frequency != "One Time"
				and len(self.get("repayment_schedule")) >= tenure
			):
				self.get("repayment_schedule")[-1].principal_amount += balance_amount
				self.get("repayment_schedule")[-1].balance_loan_amount = 0
				self.get("repayment_schedule")[-1].total_payment = (
					self.get("repayment_schedule")[-1].interest_amount
					+ self.get("repayment_schedule")[-1].principal_amount
				)
				balance_amount = 0

			if (
				self.repayment_schedule_type
				in ["Monthly as per repayment start date", "Monthly as per cycle date"]
				or self.repayment_date_on == "End of the current month"
			) and self.repayment_frequency == "Monthly":
				next_payment_date = add_single_month(payment_date)
				payment_date = next_payment_date
			elif self.repayment_frequency == "Weekly":
				payment_date = add_days(payment_date, 7)
			elif self.repayment_frequency == "Daily":
				payment_date = add_days(payment_date, 1)
			elif self.repayment_frequency == "Quarterly":
				payment_date = add_months(payment_date, 3)

			carry_forward_interest = 0
			broken_period_interest_days = 0

	def add_rows_from_prev_disbursement(self):
		loan_status = frappe.db.get_value("Loan", self.loan, "status")
		if loan_status == "Partially Disbursed" and self.repayment_schedule_type != "Line of Credit":
			prev_schedule = frappe.get_doc(
				"Loan Repayment Schedule", {"loan": self.loan, "docstatus": 1, "status": "Active"}
			)
			if prev_schedule:
				for row in prev_schedule.get("repayment_schedule"):
					if getdate(row.payment_date) < getdate(self.repayment_start_date):
						self.add_repayment_schedule_row(
							row.payment_date,
							row.principal_amount,
							row.interest_amount,
							row.total_payment,
							row.balance_loan_amount,
							row.number_of_days,
							demand_generated=row.demand_generated,
						)

				self.monthly_repayment_amount = get_monthly_repayment_amount(
					self.disbursed_amount or self.loan_amount,
					self.rate_of_interest,
					self.repayment_periods - len(self.repayment_schedule),
					self.repayment_frequency,
				)

	def validate_repayment_method(self):
		if self.repayment_method == "Repay Over Number of Periods" and not self.repayment_periods:
			frappe.throw(_("Please enter Repayment Periods"))

		if self.repayment_method == "Repay Fixed Amount per Period":
			if not self.monthly_repayment_amount:
				frappe.throw(_("Please enter repayment Amount"))
			if self.monthly_repayment_amount > self.loan_amount:
				frappe.throw(_("Monthly Repayment Amount cannot be greater than Loan Amount"))

	def get_amounts(
		self,
		payment_date,
		balance_amount,
		additional_days,
		carry_forward_interest=0,
	):
		days, months = self.get_days_and_months(payment_date, additional_days, balance_amount)
		interest_amount = flt(balance_amount * flt(self.rate_of_interest) * days / (months * 100))
		principal_amount = self.monthly_repayment_amount - flt(interest_amount)
		balance_amount = flt(balance_amount + interest_amount - self.monthly_repayment_amount)
		if balance_amount < 0:
			principal_amount += balance_amount
			balance_amount = 0.0

		if carry_forward_interest:
			interest_amount += carry_forward_interest

		total_payment = principal_amount + interest_amount

		return interest_amount, principal_amount, balance_amount, total_payment, days

	def get_days_and_months(self, payment_date, additional_days, balance_amount):
		months = 365
		if self.repayment_frequency == "Monthly":
			if self.repayment_schedule_type == "Monthly as per repayment start date":
				days = 1
				months = 12
			else:
				expected_payment_date = get_last_day(payment_date)
				if self.repayment_date_on == "Start of the next month":
					expected_payment_date = add_days(expected_payment_date, 1)

				if self.repayment_schedule_type == "Monthly as per cycle date":
					days = date_diff(payment_date, add_months(payment_date, -1))
					if additional_days < 0:
						days = date_diff(payment_date, self.posting_date)
						additional_days = 0

					if additional_days and not self.moratorium_tenure:
						self.add_broken_period_interest(balance_amount, additional_days, payment_date)
						additional_days = 0
				elif expected_payment_date == payment_date:
					# using 30 days for calculating interest for all full months
					days = 30
				else:
					days = date_diff(get_last_day(payment_date), payment_date)
		else:
			if payment_date == self.repayment_start_date:
				days = date_diff(payment_date, self.posting_date)
			elif self.repayment_frequency == "Weekly":
				days = 7
			elif self.repayment_frequency == "Daily":
				days = 1
			elif self.repayment_frequency == "Quarterly":
				days = 3
			elif self.repayment_frequency == "One Time":
				days = date_diff(self.repayment_start_date, self.posting_date)

		return days, months

	def add_broken_period_interest(self, balance_amount, additional_days, payment_date):
		interest_amount = flt(
			balance_amount * flt(self.rate_of_interest) * additional_days / (365 * 100)
		)
		payment_date = add_months(payment_date, -1)
		self.add_repayment_schedule_row(
			payment_date, 0, interest_amount, interest_amount, balance_amount, additional_days
		)

		self.broken_period_interest = interest_amount

	def add_repayment_schedule_row(
		self,
		payment_date,
		principal_amount,
		interest_amount,
		total_payment,
		balance_loan_amount,
		days,
		demand_generated=0,
	):
		self.append(
			"repayment_schedule",
			{
				"number_of_days": days,
				"payment_date": payment_date,
				"principal_amount": principal_amount,
				"interest_amount": interest_amount,
				"total_payment": total_payment,
				"balance_loan_amount": balance_loan_amount,
				"demand_generated": demand_generated,
			},
		)


def add_single_month(date):
	if getdate(date) == get_last_day(date):
		return get_last_day(add_months(date, 1))
	else:
		return add_months(date, 1)


def get_monthly_repayment_amount(loan_amount, rate_of_interest, repayment_periods, frequency):
	if frequency == "One Time":
		repayment_periods = 1

	if rate_of_interest:
		monthly_interest_rate = flt(rate_of_interest) / (get_frequency(frequency) * 100)
		monthly_repayment_amount = math.ceil(
			(loan_amount * monthly_interest_rate * (1 + monthly_interest_rate) ** repayment_periods)
			/ ((1 + monthly_interest_rate) ** repayment_periods - 1)
		)
	else:
		monthly_repayment_amount = math.ceil(flt(loan_amount) / repayment_periods)
	return monthly_repayment_amount


def get_frequency(frequency):
	return {"Monthly": 12, "Weekly": 52, "Daily": 365, "Quarterly": 4, "One Time": 1}.get(frequency)
