# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	add_months,
	cint,
	date_diff,
	flt,
	get_first_day,
	get_last_day,
	getdate,
)

from lending.loan_management.doctype.loan.loan import get_cyclic_date
from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
from lending.loan_management.doctype.loan_repayment_schedule.utils import (
	add_single_month,
	get_amounts,
	get_loan_partner_details,
	get_monthly_repayment_amount,
	set_demand,
)


# nosemgrep
class LoanRepaymentSchedule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.co_lender_schedule.co_lender_schedule import (
			CoLenderSchedule,
		)
		from lending.loan_management.doctype.repayment_schedule.repayment_schedule import (
			RepaymentSchedule,
		)

		adjusted_interest: DF.Currency
		amended_from: DF.Link | None
		broken_period_interest: DF.Currency
		broken_period_interest_days: DF.Int
		colender_schedule: DF.Table[CoLenderSchedule]
		company: DF.Link | None
		current_principal_amount: DF.Currency
		disbursed_amount: DF.Currency
		loan: DF.Link
		loan_amount: DF.Currency
		loan_disbursement: DF.Link | None
		loan_partner: DF.Link | None
		loan_partner_rate_of_interest: DF.Float
		loan_product: DF.Link | None
		loan_restructure: DF.Link | None
		maturity_date: DF.Date | None
		monthly_repayment_amount: DF.Currency
		moratorium_end_date: DF.Date | None
		moratorium_tenure: DF.Int
		moratorium_type: DF.Data | None
		partner_base_interest_rate: DF.Percent
		partner_loan_share_percentage: DF.Percent
		partner_monthly_repayment_amount: DF.Currency
		partner_repayment_schedule_type: DF.Data | None
		posting_date: DF.Datetime | None
		rate_of_interest: DF.Float
		repayment_date_on: DF.Literal["Start of the next month", "End of the current month"]
		repayment_frequency: DF.Literal[
			"Monthly", "Daily", "Weekly", "Bi-Weekly", "Quarterly", "One Time"
		]
		repayment_method: DF.Literal["", "Repay Fixed Amount per Period", "Repay Over Number of Periods"]
		repayment_periods: DF.Int
		repayment_schedule: DF.Table[RepaymentSchedule]
		repayment_schedule_type: DF.Data | None
		repayment_start_date: DF.Date | None
		restructure_type: DF.Literal["", "Normal Restructure", "Advance Payment", "Pre Payment"]
		status: DF.Literal[
			"Initiated",
			"Rejected",
			"Active",
			"Restructured",
			"Rescheduled",
			"Outdated",
			"Draft",
			"Cancelled",
			"Closed",
		]
		total_installments_overdue: DF.Int
		total_installments_paid: DF.Int
		total_installments_raised: DF.Int
		treatment_of_interest: DF.Literal["Capitalize", "Add to first repayment"]
	# end: auto-generated types

	def validate(self):
		self.number_of_rows = 0
		self.set_repayment_period()
		self.set_repayment_start_date()
		self.validate_repayment_method()
		self.make_customer_repayment_schedule()
		self.make_co_lender_schedule()
		self.reset_index()
		self.set_maturity_date()

	def reset_index(self):
		for idx, row in enumerate(self.get("repayment_schedule"), start=1):
			row.idx = idx

	def set_maturity_date(self):
		if self.get("repayment_schedule"):
			self.maturity_date = self.get("repayment_schedule")[-1].payment_date

	# nosemgrep
	def on_submit(self):
		self.number_of_rows = 0
		self.make_demand_for_advance_payment()

	def make_demand_for_advance_payment(self):
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			get_interest_for_term,
			get_last_accrual_date,
			make_loan_interest_accrual_entry,
		)

		advance_payment = ""
		if not self.restructure_type in ("Advance Payment", "Pre Payment"):
			return
		for row in self.repayment_schedule:
			if not row.demand_generated:
				advance_payment = row
				break

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		principal_balance = 0

		if self.restructure_type == "Advance Payment":
			set_demand(advance_payment.name)

		prepayment_details = frappe.db.get_value(
			"Loan Restructure",
			{"loan": self.loan, "name": self.loan_restructure},
			["unaccrued_interest", "principal_adjusted", "balance_principal"],
			as_dict=1,
		)

		interest_amount = prepayment_details.unaccrued_interest
		principal_amount = abs(prepayment_details.balance_principal)
		principal_balance = prepayment_details.balance_principal
		paid_interest_amount = interest_amount
		paid_principal_amount = principal_amount

		if flt(interest_amount) > 0:
			create_loan_demand(
				self.loan,
				self.posting_date,
				"EMI",
				"Interest",
				interest_amount,
				loan_repayment_schedule=self.name,
				loan_disbursement=self.loan_disbursement,
				repayment_schedule_detail=advance_payment.name
				if self.restructure_type == "Advance Payment"
				else None,
				paid_amount=paid_interest_amount,
			)

		create_loan_demand(
			self.loan,
			self.posting_date,
			"EMI",
			"Principal",
			principal_amount,
			loan_repayment_schedule=self.name,
			loan_disbursement=self.loan_disbursement,
			repayment_schedule_detail=advance_payment.name
			if self.restructure_type == "Advance Payment"
			else None,
			paid_amount=paid_principal_amount,
		)

		last_accrual_date = get_last_accrual_date(self.loan, self.posting_date, "Normal Interest")

		payable_interest = get_interest_for_term(
			self.company,
			self.rate_of_interest,
			self.current_principal_amount - principal_balance,
			add_days(last_accrual_date, 1),
			add_days(self.posting_date, -1),
		)

		if payable_interest > 0:
			make_loan_interest_accrual_entry(
				self.loan,
				self.current_principal_amount - principal_balance,
				flt(payable_interest, precision),
				"",
				last_accrual_date,
				add_days(self.posting_date, -1),
				"Regular",
				"Normal Interest",
				self.rate_of_interest,
				loan_repayment_schedule=self.name,
			)
		self.repayment_periods = self.number_of_rows - self.moratorium_tenure

	def on_cancel(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import reverse_demands
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		bpi_accrual = frappe.db.get_value(
			"Loan Interest Accrual",
			{
				"loan_repayment_schedule": self.name,
				"docstatus": 1,
				"interest_amount": flt(self.broken_period_interest, precision),
			},
		)

		if bpi_accrual:
			bpi_accrual_doc = frappe.get_doc("Loan Interest Accrual", bpi_accrual)
			bpi_accrual_doc.cancel()

		if cint(self.get("reverse_interest_accruals")):
			if not frappe.flags.in_test:
				frappe.enqueue(
					reverse_loan_interest_accruals,
					loan=self.loan,
					posting_date=self.posting_date,
					loan_repayment_schedule=self.name,
					queue="long",
					enqueue_after_commit=True,
				)

				frappe.enqueue(
					reverse_demands,
					loan=self.loan,
					posting_date=self.posting_date,
					loan_repayment_schedule=self.name,
					queue="long",
					enqueue_after_commit=True,
				)
			else:
				reverse_loan_interest_accruals(
					loan=self.loan,
					posting_date=self.posting_date,
					loan_repayment_schedule=self.name,
				)

				reverse_demands(
					loan=self.loan,
					posting_date=self.posting_date,
					loan_repayment_schedule=self.name,
				)

		self.ignore_linked_doctypes = ["Loan Interest Accrual", "Loan Demand"]

		self.db_set("status", "Cancelled")

	def set_repayment_period(self):
		if self.repayment_frequency == "One Time":
			self.repayment_method = "Repay Over Number of Periods"
			self.repayment_periods = 1

		if self.restructure_type and self.repayment_periods == 1:
			self.repayment_frequency = "One Time"

	def make_customer_repayment_schedule(self):
		self.set("repayment_schedule", [])

		self.broken_period_interest = 0
		(
			previous_interest_amount,
			balance_amount,
			additional_principal_amount,
			pending_prev_days,
		) = self.add_rows_from_prev_disbursement("repayment_schedule", 100, 100)

		if flt(balance_amount, self.precision) > 0:
			self.make_repayment_schedule(
				"repayment_schedule",
				previous_interest_amount,
				balance_amount,
				additional_principal_amount,
				pending_prev_days,
				self.rate_of_interest,
				100,
				100,
			)

	def make_co_lender_schedule(self):
		if not self.loan_partner:
			return

		self.set("colender_schedule", [])

		loan_partner_details = get_loan_partner_details(self.loan_partner)

		if loan_partner_details.repayment_schedule_type == "EMI (PMT) based":
			partner_loan_amount = (
				self.current_principal_amount * flt(loan_partner_details.partner_loan_share_percentage) / 100
			)
			principal_share_percentage = 100
			interest_share_percentage = 100
			rate_of_interest = self.loan_partner_rate_of_interest
		elif loan_partner_details.repayment_schedule_type == "Collection at partner's percentage":
			partner_loan_amount = self.current_principal_amount
			rate_of_interest = self.rate_of_interest
			principal_share_percentage = flt(loan_partner_details.partner_loan_share_percentage)
			interest_share_percentage = flt(loan_partner_details.partner_loan_share_percentage)
		else:
			partner_loan_amount = (
				self.current_principal_amount * flt(loan_partner_details.partner_loan_share_percentage) / 100
			)
			rate_of_interest = self.loan_partner_rate_of_interest
			principal_share_percentage = flt(loan_partner_details.partner_loan_share_percentage)
			interest_share_percentage = 100

		self.make_repayment_schedule(
			"colender_schedule",
			0,
			partner_loan_amount,
			0,
			0,
			rate_of_interest,
			principal_share_percentage,
			interest_share_percentage,
			loan_partner_details.repayment_schedule_type,
		)

	def make_repayment_schedule(
		self,
		schedule_field,
		previous_interest_amount,
		balance_amount,
		additional_principal_amount,
		pending_prev_days,
		rate_of_interest,
		principal_share_percentage,
		interest_share_percentage,
		partner_schedule_type=None,
	):
		payment_date = self.repayment_start_date
		carry_forward_interest = self.adjusted_interest
		moratorium_interest = 0
		row = 0
		if not self.restructure_type and self.repayment_method != "Repay Fixed Amount per Period":
			monthly_repayment_amount = get_monthly_repayment_amount(
				balance_amount, rate_of_interest, self.repayment_periods, self.repayment_frequency
			)
		else:
			monthly_repayment_amount = self.monthly_repayment_amount

		if not self.restructure_type:
			if (
				self.moratorium_tenure
				and self.repayment_frequency == "Monthly"
				and self.repayment_schedule_type == "Monthly as per cycle date"
			):
				payment_date = self.repayment_start_date
				self.repayment_start_date = add_months(payment_date, self.moratorium_tenure)
				self.moratorium_end_date = add_months(self.repayment_start_date, -1)
			elif self.moratorium_tenure and self.repayment_frequency == "Monthly":
				self.moratorium_end_date = add_months(self.repayment_start_date, self.moratorium_tenure)
				if self.repayment_schedule_type == "Pro-rated calendar months":
					self.moratorium_end_date = add_days(self.moratorium_end_date, -1)

		tenure = self.get_applicable_tenure(payment_date)
		additional_days = cint(self.broken_period_interest_days)

		if len(self.get(schedule_field)) > 0:
			self.broken_period_interest_days = 0

		if additional_days < 0:
			self.broken_period_interest_days = 0

		while balance_amount > 0:
			if self.moratorium_tenure and self.repayment_frequency == "Monthly":
				if getdate(payment_date) > getdate(self.moratorium_end_date):
					if (
						self.moratorium_type == "EMI"
						and self.treatment_of_interest == "Capitalize"
						and moratorium_interest
					):
						balance_amount = self.loan_amount + moratorium_interest
						monthly_repayment_amount = get_monthly_repayment_amount(
							balance_amount, rate_of_interest, self.repayment_periods, self.repayment_frequency
						)
						moratorium_interest = 0

			prev_balance_amount = balance_amount

			payment_days, months = self.get_days_and_months(
				payment_date,
				additional_days,
				balance_amount,
				rate_of_interest,
				schedule_field,
				principal_share_percentage,
				interest_share_percentage,
			)

			(
				interest_amount,
				principal_amount,
				balance_amount,
				total_payment,
				days,
				previous_interest_amount,
			) = get_amounts(
				balance_amount,
				rate_of_interest,
				payment_days,
				months,
				monthly_repayment_amount,
				carry_forward_interest,
				previous_interest_amount,
				additional_principal_amount,
				pending_prev_days,
			)

			if (
				schedule_field == "colender_schedule"
				and partner_schedule_type == "POS reduction plus interest at partner ROI"
				and row <= len(self.get("repayment_schedule")) - 1
			):
				principal_amount = self.get("repayment_schedule")[row].principal_amount
				balance_amount = prev_balance_amount - (principal_amount * principal_share_percentage / 100)
				row = row + 1

			if (
				self.moratorium_end_date and self.moratorium_tenure and self.repayment_frequency == "Monthly"
			):
				if getdate(payment_date) <= getdate(self.moratorium_end_date):
					principal_amount = 0
					balance_amount = self.current_principal_amount
					moratorium_interest += interest_amount

					if self.moratorium_type == "EMI":
						total_payment = 0
						interest_amount = 0
					else:
						total_payment = interest_amount

				elif (
					self.moratorium_type == "EMI"
					and self.treatment_of_interest == "Add to first repayment"
					and moratorium_interest
				):
					interest_amount += moratorium_interest
					total_payment = principal_amount + interest_amount
					moratorium_interest = 0

			self.add_repayment_schedule_row(
				payment_date,
				principal_amount,
				interest_amount,
				total_payment,
				balance_amount,
				days,
				repayment_schedule_field=schedule_field,
				principal_share_percentage=principal_share_percentage,
				interest_share_percentage=interest_share_percentage,
			)

			# All the residue amount is added to the last row for "Repay Over Number of Periods"
			#
			# Also, when such a Repayment Schedule is rescheduled, its repayment_method changes to Repay Fixed Amount per Period
			# Here, the tenure shouldn't change. Thus, if this is a restructed repayment schedule, the last row is all the residue amount left.
			# This is a special case.

			if (
				self.repayment_method == "Repay Over Number of Periods"
				or (self.restructure_type and self.repayment_method == "Repay Fixed Amount per Period")
			) and len(self.get(schedule_field)) >= tenure:
				self.get(schedule_field)[-1].principal_amount += balance_amount
				self.get(schedule_field)[-1].balance_loan_amount = 0
				self.get(schedule_field)[-1].total_payment = (
					self.get(schedule_field)[-1].interest_amount + self.get(schedule_field)[-1].principal_amount
				)
				balance_amount = 0

			payment_date = self.get_next_payment_date(payment_date)
			carry_forward_interest = 0
			additional_days = 0
			additional_principal_amount = 0
			pending_prev_days = 0

		if schedule_field == "repayment_schedule" and not self.restructure_type:
			if self.repayment_frequency == "One Time":
				self.monthly_repayment_amount = self.get(schedule_field)[0].total_payment
			else:
				self.monthly_repayment_amount = monthly_repayment_amount
		else:
			self.repayment_periods = self.number_of_rows

	def get_next_payment_date(self, payment_date):
		if (
			self.repayment_schedule_type
			in [
				"Monthly as per repayment start date",
				"Monthly as per cycle date",
				"Line of Credit",
				"Pro-rated calendar months",
			]
		) and self.repayment_frequency == "Monthly":
			next_payment_date = add_single_month(payment_date)
			payment_date = next_payment_date
		elif self.repayment_frequency == "Bi-Weekly":
			payment_date = add_days(payment_date, 14)
		elif self.repayment_frequency == "Weekly":
			payment_date = add_days(payment_date, 7)
		elif self.repayment_frequency == "Daily":
			payment_date = add_days(payment_date, 1)
		elif self.repayment_frequency == "Quarterly":
			payment_date = add_months(payment_date, 3)

		return payment_date

	def get_applicable_tenure(self, payment_date):
		loan_status = frappe.db.get_value("Loan", self.loan, "status") or "Sanctioned"

		if self.repayment_frequency == "Monthly" and (
			loan_status == "Sanctioned" or self.repayment_schedule_type == "Line of Credit"
		):
			tenure = self.repayment_periods
			if self.repayment_frequency == "Monthly" and self.moratorium_tenure:
				tenure += cint(self.moratorium_tenure)
		elif self.restructure_type in ("Advance Payment", "Pre Payment") and self.moratorium_tenure:
			tenure = self.repayment_periods + self.moratorium_tenure
		elif loan_status == "Partially Disbursed":
			prev_schedule = frappe.db.get_value(
				"Loan Repayment Schedule", {"loan": self.loan, "docstatus": 1, "status": "Active"}
			)
			tenure = frappe.db.count("Repayment Schedule", {"parent": prev_schedule})
		else:
			tenure = self.repayment_periods

		if (
			self.restructure_type != "Normal Restructure"
			and self.repayment_frequency == "Monthly"
			or (self.restructure_type == "Pre Payment" and self.repayment_frequency != "One Time")
		):
			self.broken_period_interest_days = date_diff(add_months(payment_date, -1), self.posting_date)
			if (
				self.broken_period_interest_days > 0
				and not self.moratorium_tenure
				and loan_status != "Partially Disbursed"
			):
				tenure += 1

		return tenure

	def add_rows_from_prev_disbursement(
		self, schedule_field, principal_share_percentage, interest_share_percentage=100
	):
		previous_interest_amount = 0
		completed_tenure = 0
		balance_principal_amount = self.current_principal_amount
		additional_principal_amount = 0
		pending_prev_days = 0

		loan_status = frappe.db.get_value("Loan", self.loan, "status")
		if (
			(loan_status == "Partially Disbursed" and self.repayment_schedule_type != "Line of Credit")
			or self.restructure_type in ("Advance Payment", "Pre Payment")
			and self.repayment_frequency != "One Time"
		):
			filters = {"loan": self.loan, "docstatus": 1, "status": "Active"}

			if self.loan_disbursement and self.repayment_schedule_type == "Line of Credit":
				filters["loan_disbursement"] = self.loan_disbursement

			prev_schedule = frappe.get_doc("Loan Repayment Schedule", filters)

			self.total_installments_raised = prev_schedule.total_installments_raised
			self.total_installments_paid = prev_schedule.total_installments_paid
			self.total_installments_overdue = prev_schedule.total_installments_overdue

			if prev_schedule:
				if self.restructure_type:
					self.loan_disbursement = prev_schedule.loan_disbursement

				prev_repayment_date = prev_schedule.posting_date
				prev_balance_amount = prev_schedule.current_principal_amount
				self.monthly_repayment_amount = prev_schedule.monthly_repayment_amount
				first_date = prev_schedule.get(schedule_field)[0].payment_date
				previous_broken_period_interest = prev_schedule.broken_period_interest

				if getdate(self.repayment_start_date) > getdate(prev_schedule.repayment_start_date):
					for row in prev_schedule.get(schedule_field):
						if getdate(row.payment_date) < getdate(self.posting_date) or (
							getdate(row.payment_date) == getdate(self.posting_date) and self.restructure_type
						):

							if getdate(row.payment_date) == getdate(self.posting_date) and self.restructure_type in (
								"Pre Payment",
								"Advance Payment",
							):
								row.balance_loan_amount = self.current_principal_amount

							self.add_repayment_schedule_row(
								row.payment_date,
								row.principal_amount,
								row.interest_amount,
								row.total_payment,
								row.balance_loan_amount,
								row.number_of_days,
								demand_generated=row.demand_generated,
								repayment_schedule_field=schedule_field,
							)
							prev_repayment_date = row.payment_date
							prev_balance_amount = row.balance_loan_amount
							if row.principal_amount:
								completed_tenure += 1
						elif getdate(self.posting_date) > row.payment_date:
							self.repayment_start_date = row.payment_date
							prev_repayment_date = row.payment_date
							break

					if (
						self.moratorium_end_date
						and getdate(self.posting_date) <= getdate(self.moratorium_end_date)
						and self.restructure_type
					):
						self.monthly_repayment_amount = get_monthly_repayment_amount(
							self.current_principal_amount,
							self.rate_of_interest,
							self.repayment_periods,
							self.repayment_frequency,
						)
						return (
							previous_interest_amount,
							self.current_principal_amount,
							additional_principal_amount,
							pending_prev_days,
						)

					if self.restructure_type in ("Pre Payment", "Advance Payment") and completed_tenure >= 1:
						self.get("repayment_schedule")[
							completed_tenure - 1
						].balance_loan_amount = self.current_principal_amount

					if not self.restructure_type:
						self.broken_period_interest = prev_schedule.broken_period_interest

					pending_prev_days = date_diff(self.posting_date, prev_repayment_date)

					if pending_prev_days > 0:
						previous_interest_amount += flt(
							prev_balance_amount * flt(self.rate_of_interest) * pending_prev_days / (36500)
						)
				elif date_diff(add_months(self.repayment_start_date, -1), self.posting_date) > 0:
					self.repayment_start_date = prev_schedule.repayment_start_date
					prev_days = date_diff(self.posting_date, prev_schedule.posting_date)
					interest_amount = flt(prev_balance_amount * flt(self.rate_of_interest) * prev_days / (36500))

					if self.repayment_frequency != "One Time":
						self.broken_period_interest += interest_amount
				else:
					prev_balance_amount = prev_schedule.current_principal_amount
					previous_interest_amount = prev_schedule.get(schedule_field)[0].interest_amount
					additional_principal_amount = self.disbursed_amount

				if self.restructure_type == "Advance Payment":
					unaccrued_interest = frappe.db.get_value(
						"Loan Restructure", self.loan_restructure, "unaccrued_interest"
					)

					interest_amount = unaccrued_interest

					paid_principal_amount = self.monthly_repayment_amount - interest_amount
					total_payment = paid_principal_amount + interest_amount
					balance_principal_amount = self.current_principal_amount
					previous_interest_amount = 0

					if self.repayment_schedule_type == "Monthly as per cycle date":
						if not previous_broken_period_interest:
							ignore_bpi = True
						else:
							ignore_bpi = False

						next_emi_date = get_cyclic_date(
							self.loan_product, prev_repayment_date, ignore_bpi=ignore_bpi
						)
					else:
						next_emi_date = self.get_next_payment_date(prev_repayment_date)

					self.repayment_start_date = frappe.db.get_value(
						"Loan Restructure", self.loan_restructure, "repayment_start_date"
					)
					self.add_repayment_schedule_row(
						next_emi_date,
						paid_principal_amount,
						interest_amount,
						total_payment,
						balance_principal_amount,
						pending_prev_days,
						0,
						repayment_schedule_field=schedule_field,
						principal_share_percentage=principal_share_percentage,
						interest_share_percentage=interest_share_percentage,
					)

					pending_prev_days = date_diff(next_emi_date, self.posting_date)

					if pending_prev_days > 0:
						previous_interest_amount += flt(
							balance_principal_amount * flt(self.rate_of_interest) * pending_prev_days / (36500)
						)

					self.repayment_start_date = self.get_next_payment_date(next_emi_date)

					completed_tenure += 1
				elif not self.restructure_type:
					self.current_principal_amount = self.disbursed_amount + prev_balance_amount
					balance_principal_amount = self.current_principal_amount

				if self.repayment_method == "Repay Over Number of Periods" and not self.restructure_type:
					self.monthly_repayment_amount = get_monthly_repayment_amount(
						balance_principal_amount,
						self.rate_of_interest,
						self.repayment_periods - completed_tenure,
						self.repayment_frequency,
					)

				if self.restructure_type == "Pre Payment" and self.repayment_frequency != "One Time":
					interest_amount = 0
					principal_amount = 0

					# Pre payment made even before the first EMI
					if getdate(self.posting_date) < getdate(first_date):
						next_emi_date = get_cyclic_date(self.loan_product, self.posting_date, ignore_bpi=True)
					else:
						next_emi_date = self.get_next_payment_date(prev_repayment_date)

					pending_prev_days = date_diff(next_emi_date, self.posting_date)

					if pending_prev_days > 0:
						interest_amount = flt(
							self.current_principal_amount * flt(self.rate_of_interest) * pending_prev_days / (36500)
						)

						if self.current_principal_amount > self.monthly_repayment_amount:
							principal_amount = self.monthly_repayment_amount - interest_amount
						else:
							principal_amount = self.current_principal_amount

					total_payment = principal_amount + interest_amount

					balance_principal_amount = self.current_principal_amount - principal_amount
					self.add_repayment_schedule_row(
						next_emi_date,
						principal_amount,
						interest_amount,
						total_payment,
						balance_principal_amount,
						pending_prev_days,
						0,
						repayment_schedule_field=schedule_field,
						principal_share_percentage=principal_share_percentage,
						interest_share_percentage=interest_share_percentage,
					)

					pending_prev_days = 0
					previous_interest_amount = 0
					additional_principal_amount = 0
					self.repayment_start_date = self.get_next_payment_date(next_emi_date)

		return (
			previous_interest_amount,
			balance_principal_amount,
			additional_principal_amount,
			pending_prev_days,
		)

	def set_repayment_start_date(self):
		if self.repayment_schedule_type == "Pro-rated calendar months" and not self.restructure_type:
			repayment_start_date = get_last_day(self.posting_date)
			if self.repayment_date_on == "Start of the next month":
				repayment_start_date = add_days(repayment_start_date, 1)

			self.repayment_start_date = repayment_start_date

	def validate_repayment_method(self):
		if not self.repayment_start_date:
			frappe.throw(_("Repayment Start Date is mandatory for term loans"))

		if self.repayment_method == "Repay Over Number of Periods" and not self.repayment_periods:
			frappe.throw(_("Please enter Repayment Periods"))

		if self.repayment_method == "Repay Fixed Amount per Period" and not self.restructure_type:
			self.monthly_repayment_amount = frappe.db.get_value(
				"Loan", self.loan, "monthly_repayment_amount"
			)
			if not self.monthly_repayment_amount:
				frappe.throw(_("Please enter monthly repayment amount"))
			if self.monthly_repayment_amount > self.loan_amount:
				frappe.throw(_("Monthly Repayment Amount cannot be greater than Loan Amount"))

	def get_days_and_months(
		self,
		payment_date,
		additional_days,
		balance_amount,
		rate_of_interest,
		schedule_field,
		principal_share_percentage,
		interest_share_percentage,
	):
		months = 365
		if self.repayment_frequency == "Monthly":
			expected_payment_date = get_last_day(payment_date)
			if self.repayment_date_on == "Start of the next month":
				expected_payment_date = add_days(expected_payment_date, 1)

			if self.repayment_schedule_type in (
				"Monthly as per cycle date",
				"Line of Credit",
				"Monthly as per repayment start date",
				"Pro-rated calendar months",
			):
				days = date_diff(payment_date, add_months(payment_date, -1))
				if (
					additional_days < 0
					or (additional_days > 0 and self.moratorium_tenure and not self.restructure_type)
					or (additional_days > 0 and self.restructure_type == "Normal Restructure")
				):
					days = date_diff(payment_date, self.posting_date)
					additional_days = 0

				if additional_days and not self.moratorium_tenure and not self.restructure_type:
					self.add_broken_period_interest(
						balance_amount,
						rate_of_interest,
						additional_days,
						payment_date,
						schedule_field,
						principal_share_percentage=principal_share_percentage,
						interest_share_percentage=interest_share_percentage,
					)
					additional_days = 0

			elif expected_payment_date == payment_date:
				if self.repayment_schedule_type == "Pro-rated calendar months":
					if payment_date == self.repayment_start_date:
						days = date_diff(payment_date, self.posting_date)
					elif self.repayment_date_on == "End of the current month":
						days = date_diff(payment_date, get_first_day(payment_date)) + 1
					else:
						days = date_diff(get_last_day(payment_date), payment_date) + 1
				else:
					# using 30 days for calculating interest for all full months
					days = 30
			else:
				if payment_date == self.repayment_start_date:
					days = date_diff(payment_date, self.posting_date)
				else:
					days = date_diff(get_last_day(payment_date), payment_date)
		else:
			if payment_date == self.repayment_start_date:
				days = date_diff(payment_date, self.posting_date)
			elif self.repayment_frequency == "Bi-Weekly":
				days = 14
			elif self.repayment_frequency == "Weekly":
				days = 7
			elif self.repayment_frequency == "Daily":
				days = 1
			elif self.repayment_frequency == "Quarterly":
				days = 3
			elif self.repayment_frequency == "One Time":
				days = date_diff(self.repayment_start_date, self.posting_date)

		return days, months

	def add_broken_period_interest(
		self,
		balance_amount,
		rate_of_interest,
		additional_days,
		payment_date,
		schedule_field,
		principal_share_percentage,
		interest_share_percentage,
	):
		interest_amount = flt(balance_amount * flt(rate_of_interest) * additional_days / (365 * 100))

		if schedule_field == "repayment_schedule":
			self.broken_period_interest += interest_amount

		payment_date = add_months(payment_date, -1)
		self.add_repayment_schedule_row(
			payment_date,
			0,
			interest_amount,
			interest_amount,
			balance_amount,
			additional_days,
			repayment_schedule_field=schedule_field,
			principal_share_percentage=principal_share_percentage,
			interest_share_percentage=interest_share_percentage,
		)

	def add_repayment_schedule_row(
		self,
		payment_date,
		principal_amount,
		interest_amount,
		total_payment,
		balance_loan_amount,
		days,
		demand_generated=0,
		repayment_schedule_field=None,
		principal_share_percentage=100,
		interest_share_percentage=100,
	):
		if (
			self.moratorium_type == "EMI"
			and self.moratorium_end_date
			and getdate(payment_date) <= getdate(self.moratorium_end_date)
		):
			demand_generated = 1

		if not repayment_schedule_field:
			repayment_schedule_field = "repayment_schedule"

		interest_amount = interest_amount * interest_share_percentage / 100
		principal_amount = principal_amount * principal_share_percentage / 100
		total_payment = principal_amount + interest_amount

		if repayment_schedule_field == "colender_schedule" and not self.partner_monthly_repayment_amount:
			self.partner_monthly_repayment_amount = total_payment

		self.append(
			repayment_schedule_field,
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

		if repayment_schedule_field != "colender_schedule":
			self.increment_number_of_rows(payment_date)

	def increment_number_of_rows(self, payment_date):
		self.number_of_rows += 1
