# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import functions as fn
from frappe.utils import add_days, cint, flt, getdate, nowdate


class InstallmentSkip:
	"""Validates and prepares a Loan Restructure of type "Installment Skip".

	The skipped installments are rebuilt by Loan Repayment Schedule as zero rows. Interest of
	a skipped period keeps accruing and is billed with the next installment (never waived).
	"""

	def __init__(self, restructure):
		self.doc = restructure
		self.schedule = self.get_active_schedule()
		self.open_rows = self.get_open_rows()

	def prepare(self):
		self.validate_loan_status()
		self.validate_after_last_demand()
		self.validate_nothing_due_is_unbilled()
		self.validate_no_overdue()
		self.validate_skipped_installments()
		self.validate_nothing_billed_ahead()
		self.set_terms()

	def validate_loan_status(self):
		# The schedule of a Partially Disbursed loan is rebuilt on every disbursement
		if frappe.db.get_value("Loan", self.doc.loan, "status") == "Partially Disbursed":
			frappe.throw(_("Installments cannot be skipped until the loan is fully disbursed"))

	def get_active_schedule(self):
		filters = {"loan": self.doc.loan, "docstatus": 1, "status": "Active"}
		if self.doc.loan_disbursement:
			filters["loan_disbursement"] = self.doc.loan_disbursement

		schedule = frappe.db.get_value("Loan Repayment Schedule", filters, "name")
		if not schedule:
			frappe.throw(_("No active repayment schedule found for Loan {0}").format(self.doc.loan))

		return frappe.get_doc("Loan Repayment Schedule", schedule)

	def get_open_rows(self):
		"""Installments for which no demand is raised yet. Only these can be skipped."""
		rows = [row for row in self.schedule.repayment_schedule if not row.demand_generated]
		return sorted(rows, key=lambda row: getdate(row.payment_date))

	def validate_after_last_demand(self):
		# Interest up to a billed installment is already in its demand. Starting earlier bills it twice.
		processed_dates = get_last_processed_dates(self.doc.loan)
		if processed_dates and getdate(self.doc.restructure_date) < max(processed_dates):
			frappe.throw(
				_("Restructure Date cannot be before {0}, the last date for which interest is billed").format(
					max(processed_dates)
				)
			)

	def validate_nothing_due_is_unbilled(self):
		restructure_date = getdate(self.doc.restructure_date)
		unbilled = [
			row for row in self.open_rows if row.total_payment and getdate(row.payment_date) < restructure_date
		]
		if unbilled:
			frappe.throw(
				_("Installment of {0} is already due but not billed. Run loan demand processing first.").format(
					getdate(unbilled[0].payment_date)
				)
			)

	def validate_no_overdue(self):
		if flt(self.doc.total_overdue_amount) > 0:
			frappe.throw(
				_(
					"Installments cannot be skipped while the loan has unpaid dues of {0}. "
					"Collect them first. For a loan repaid from salary, submit the pending Salary Slip."
				).format(self.doc.total_overdue_amount)
			)

	def validate_skipped_installments(self):
		skipped = self.doc.get("skipped_installments")
		if not skipped:
			frappe.throw(_("Please select at least one installment to skip"))

		open_rows = {getdate(row.payment_date): row for row in self.open_rows}
		seen = set()

		for skip in skipped:
			date = getdate(skip.payment_date)
			row = open_rows.get(date)

			if date in seen:
				frappe.throw(_("Row {0}: Installment of {1} is selected more than once").format(skip.idx, date))
			if not row:
				frappe.throw(
					_(
						"Row {0}: No open installment on {1}. It is already due, paid or skipped."
					).format(skip.idx, date)
				)
			if date < getdate(self.doc.restructure_date):
				frappe.throw(_("Row {0}: Installment of {1} is before the restructure date").format(skip.idx, date))

			seen.add(date)
			skip.principal_amount = row.principal_amount
			skip.interest_amount = row.interest_amount
			skip.total_payment = row.total_payment

	def validate_nothing_billed_ahead(self):
		# Rows after the first open one are rebuilt, so none of them may be billed already
		first_open = getdate(self.open_rows[0].payment_date)
		for row in self.schedule.repayment_schedule:
			if getdate(row.payment_date) > first_open and row.demand_generated and row.total_payment:
				frappe.throw(
					_("Installment of {0} is already billed after the installments to skip.").format(
						getdate(row.payment_date)
					)
				)

	def get_row_counts(self):
		"""(history, carried skips, open) rows of the schedule being replaced"""
		first_open = getdate(self.open_rows[0].payment_date)
		rows = self.schedule.repayment_schedule
		history = len([row for row in rows if getdate(row.payment_date) < first_open])
		carried = len(
			[
				row
				for row in rows
				if getdate(row.payment_date) > first_open and row.demand_generated and not row.total_payment
			]
		)
		return history, carried, len(self.open_rows)

	def repayment_frequency(self):
		return self.schedule.repayment_frequency

	def update_loan_terms(self, cancel=0):
		"""Show the new terms on the Loan. Payment history on the Loan stays as it is."""
		schedule = self.get_active_schedule()
		doc = self.doc

		# The Loan counts installments without the broken period row, so add only the rows gained
		old_row_count = doc.new_repayment_period_in_months
		if doc.new_repayment_method == "Repay Fixed Amount per Period":
			old_row_count -= len(doc.get("skipped_installments"))
		new_periods = cint(doc.old_tenure) + len(schedule.repayment_schedule) - old_row_count

		frappe.db.set_value(
			"Loan",
			doc.loan,
			{
				"monthly_repayment_amount": doc.old_emi if cancel else schedule.monthly_repayment_amount,
				"repayment_periods": doc.old_tenure if cancel else new_periods,
				"total_payment": sum(flt(row.total_payment) for row in schedule.repayment_schedule),
				"total_interest_payable": sum(flt(row.interest_amount) for row in schedule.repayment_schedule),
			},
		)

	def emi_periods(self):
		"""Installments that carry principal when the maturity is kept"""
		return len(self.open_rows) - len(self.doc.get("skipped_installments"))

	def set_terms(self):
		doc = self.doc
		skip_count = len(doc.get("skipped_installments"))
		history, carried, open_count = self.get_row_counts()

		# Interest is always billed later. Never capitalised or waived by a skip.
		doc.treatment_of_normal_interest = "Add To First EMI"
		doc.unaccrued_interest_treatment = "Add To First EMI"
		doc.repayment_start_date = self.open_rows[0].payment_date
		doc.old_tenure = doc.old_tenure or frappe.db.get_value("Loan", doc.loan, "repayment_periods")
		doc.new_repayment_method = doc.new_repayment_method or "Repay Fixed Amount per Period"

		# The new schedule keeps the earlier rows, so the period count covers them too
		if doc.new_repayment_method == "Repay Fixed Amount per Period":
			# Same EMI, so every skipped installment adds one period at the end
			doc.new_monthly_repayment_amount = self.schedule.monthly_repayment_amount
			doc.new_repayment_period_in_months = history + carried + open_count + skip_count
		else:
			# Same maturity, so EMI is recalculated over the installments that remain
			if self.emi_periods() < 1:
				frappe.throw(_("At least one installment must remain after the skipped installments"))
			doc.new_repayment_period_in_months = history + carried + open_count


@frappe.whitelist()
def get_open_installments(loan: str, loan_disbursement: str | None = None):
	"""Installments of the active schedule that can still be skipped"""
	frappe.has_permission("Loan", "read", loan, throw=True)

	skip = InstallmentSkip(frappe._dict(loan=loan, loan_disbursement=loan_disbursement))
	skip_date = get_skip_date(loan)
	return [
		{
			"payment_date": row.payment_date,
			"principal_amount": row.principal_amount,
			"interest_amount": row.interest_amount,
			"total_payment": row.total_payment,
		}
		for row in skip.open_rows
		if row.total_payment and getdate(row.payment_date) >= skip_date
	]


@frappe.whitelist()
def skip_installments(
	loan: str,
	skipped_dates: str,
	new_repayment_method: str | None = None,
	reason: str | None = None,
	approve: int = 1,
	restructure_date: str | None = None,
):
	"""One step entry point. Creates the Loan Restructure and approves it when asked to.

	Payroll needs nothing else: the skipped installment never gets a demand, so the
	Salary Slip does not pick it up.
	"""
	frappe.has_permission("Loan Restructure", "create", throw=True)

	from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
		process_daily_loan_demands,
	)

	# Installments due before the skip date must be billed before the schedule is rebuilt.
	# A Loan Manager cannot submit Process Loan Demand, so permission is checked above instead.
	process_daily_loan_demands(
		loan=loan,
		posting_date=add_days(getdate(restructure_date or nowdate()), -1),
		ignore_permissions=True,
	)

	restructure = frappe.new_doc("Loan Restructure")
	restructure.update(
		{
			"loan": loan,
			"restructure_date": get_skip_date(loan, restructure_date),
			"restructure_type": "Installment Skip",
			"new_repayment_method": new_repayment_method,
			"reason_for_restructure": reason,
		}
	)
	for date in frappe.parse_json(skipped_dates):
		restructure.append("skipped_installments", {"payment_date": date})

	restructure.submit()

	if cint(approve):
		frappe.has_permission("Loan Restructure", "write", restructure.name, throw=True)
		restructure.status = "Approved"
		restructure.save()

	return restructure.name


def get_skip_date(loan, restructure_date=None):
	"""A restructure cannot start before interest is accrued or before an installment is billed.
	Both can be ahead of today, e.g. a payroll run for a later period, so start after them."""
	skip_date = getdate(restructure_date or nowdate())
	return max([skip_date, *get_last_processed_dates(loan)])


def get_last_processed_dates(loan):
	LoanInterestAccrual = frappe.qb.DocType("Loan Interest Accrual")
	LoanDemand = frappe.qb.DocType("Loan Demand")

	last_accrual_date = (
		frappe.qb.from_(LoanInterestAccrual)
		.select(fn.Max(LoanInterestAccrual.posting_date))
		.where((LoanInterestAccrual.loan == loan) & (LoanInterestAccrual.docstatus == 1))
	).run()[0][0]
	last_demand_date = (
		frappe.qb.from_(LoanDemand)
		.select(fn.Max(LoanDemand.demand_date))
		.where((LoanDemand.loan == loan) & (LoanDemand.docstatus == 1))
	).run()[0][0]

	return [getdate(date) for date in (last_accrual_date, last_demand_date) if date]
