# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import functions as fn
from frappe.utils import add_days, cint, flt, getdate, nowdate

from lending.loan_management.doctype.loan_repayment_schedule.skip_schedule_rows import (
	get_approved_skipped_dates,
)


class InstallmentSkip:
	"""Validates and prepares a Loan Restructure of type "Installment Skip".

	The skipped installments are rebuilt by Loan Repayment Schedule as zero rows. Interest of
	a skipped period keeps accruing and is added to the next installment demand (never waived).
	"""

	def __init__(self, restructure):
		self.doc = restructure
		self.schedule = self.get_active_schedule()
		self.upcoming_rows = self.get_upcoming_rows()

	def prepare(self):
		self.validate_loan()
		self.validate_after_last_demand()
		self.validate_demand_generated_for_due_installments()
		self.validate_no_overdue()
		self.validate_skipped_installments()
		self.validate_no_demand_generated_ahead()
		self.set_terms()

	def validate_loan(self):
		loan = frappe.db.get_value(
			"Loan",
			self.doc.loan,
			["status", "repayment_schedule_type", "loan_partner", "repayment_frequency"],
			as_dict=True,
		)

		# The schedule of a Partially Disbursed loan is rebuilt on every disbursement
		if loan.status == "Partially Disbursed":
			frappe.throw(_("Installments cannot be skipped until the loan is fully disbursed"))

		# These loans have more than one schedule to rebuild, which a skip does not handle
		if loan.repayment_schedule_type == "Line of Credit" or loan.loan_partner:
			frappe.throw(_("Installments cannot be skipped for a Line of Credit or a co-lender loan"))

		if loan.repayment_frequency == "One Time":
			frappe.throw(_("Installments cannot be skipped for a loan repaid in one payment"))

	def validate_demand_not_generated_since_request(self):
		"""The schedule is built when the request is made. Approval must not follow a demand
		generated for a skipped date after that."""
		dates = [getdate(row.payment_date) for row in self.doc.get("skipped_installments")]
		if frappe.db.exists(
			"Loan Demand", {"loan": self.doc.loan, "docstatus": 1, "demand_date": ("in", dates)}
		):
			frappe.throw(_("A demand is already generated for an installment to skip. Create a new request."))

	def validate_latest_installment_skip(self):
		"""Cancelling an older skip would bring back a schedule that is no longer the latest"""
		filters = {"loan": self.doc.loan, "docstatus": 1, "status": "Active"}
		if self.doc.loan_disbursement:
			filters["loan_disbursement"] = self.doc.loan_disbursement

		latest = frappe.db.get_value("Loan Repayment Schedule", filters, "loan_restructure")
		if latest != self.doc.name:
			frappe.throw(_("Cancel the later restructure of this loan first"))

	def get_active_schedule(self):
		filters = {"loan": self.doc.loan, "docstatus": 1, "status": "Active"}
		if self.doc.loan_disbursement:
			filters["loan_disbursement"] = self.doc.loan_disbursement

		schedule = frappe.db.get_value("Loan Repayment Schedule", filters, "name")
		if not schedule:
			frappe.throw(_("No active repayment schedule found for Loan {0}").format(self.doc.loan))

		return frappe.get_doc("Loan Repayment Schedule", schedule)

	def get_upcoming_rows(self):
		"""Installments for which no demand is generated yet. Only these can be skipped."""
		rows = [row for row in self.schedule.repayment_schedule if not row.demand_generated]
		return sorted(rows, key=lambda row: getdate(row.payment_date))

	def validate_after_last_demand(self):
		# Interest up to an installment with a demand is already in that demand. Starting earlier demands it twice.
		processed_dates = get_last_accrual_and_demand_dates(self.doc.loan)
		if processed_dates and getdate(self.doc.restructure_date) < max(processed_dates):
			frappe.throw(
				_("Restructure Date cannot be before {0}, the last date for which a demand is generated").format(
					max(processed_dates)
				)
			)

	def validate_demand_generated_for_due_installments(self):
		restructure_date = getdate(self.doc.restructure_date)
		rows_without_demand = [
			row for row in self.upcoming_rows if row.total_payment and getdate(row.payment_date) < restructure_date
		]
		if rows_without_demand:
			frappe.throw(
				_("Installment of {0} is already due but its demand is not generated. Run loan demand processing first.").format(
					getdate(rows_without_demand[0].payment_date)
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

		upcoming_rows = {getdate(row.payment_date): row for row in self.upcoming_rows}
		seen = set()

		for skip in skipped:
			date = getdate(skip.payment_date)
			row = upcoming_rows.get(date)

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

	def validate_no_demand_generated_ahead(self):
		# Rows after the first upcoming one are rebuilt, so none of them may have a demand already
		first_open = getdate(self.upcoming_rows[0].payment_date)
		for row in self.schedule.repayment_schedule:
			if getdate(row.payment_date) > first_open and row.demand_generated and row.total_payment:
				frappe.throw(
					_("Installment of {0} already has a demand generated after the installments to skip.").format(
						getdate(row.payment_date)
					)
				)

	def get_row_counts(self):
		"""(completed, earlier skips, upcoming) rows of the schedule being replaced"""
		first_open = getdate(self.upcoming_rows[0].payment_date)
		rows = self.schedule.repayment_schedule
		completed = len([row for row in rows if getdate(row.payment_date) < first_open])
		# Earlier skips count even when they are at the end of the term and have no row
		earlier_skips = len(
			[date for date in get_approved_skipped_dates(self.doc.loan, self.doc.name) if date > first_open]
		)
		return completed, earlier_skips, len(self.upcoming_rows)

	def repayment_frequency(self):
		return self.schedule.repayment_frequency

	def update_loan_terms(self, cancel=0):
		"""Show the new terms on the Loan. Repayment totals paid so far on the Loan stay as they are."""
		schedule = self.get_active_schedule()
		doc = self.doc

		# The Loan counts installments without the broken period row, so add only the rows gained
		new_periods = cint(doc.old_tenure) + len(schedule.repayment_schedule) - self.get_replaced_row_count(schedule)

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

	def get_replaced_row_count(self, schedule):
		"""Rows of the schedule that this skip replaced"""
		replaced = frappe.db.get_value(
			"Loan Repayment Schedule",
			{
				"loan": self.doc.loan,
				"docstatus": 1,
				"status": "Rescheduled",
				"creation": ("<", schedule.creation),
			},
			"name",
			order_by="creation desc",
		)
		return frappe.db.count("Repayment Schedule", {"parent": replaced}) if replaced else 0

	def emi_periods(self):
		"""Installments that carry principal when the maturity is kept"""
		return len(self.upcoming_rows) - len(self.doc.get("skipped_installments"))

	def set_terms(self):
		doc = self.doc
		skip_count = len(doc.get("skipped_installments"))
		completed, earlier_skips, upcoming_count = self.get_row_counts()

		# Interest is always demanded later. Never capitalised or waived by a skip.
		doc.treatment_of_normal_interest = "Add To First EMI"
		doc.unaccrued_interest_treatment = "Add To First EMI"
		doc.repayment_start_date = self.upcoming_rows[0].payment_date
		doc.old_tenure = doc.old_tenure or frappe.db.get_value("Loan", doc.loan, "repayment_periods")
		doc.new_repayment_method = doc.new_repayment_method or "Repay Fixed Amount per Period"

		# The new schedule keeps the earlier rows, so the period count covers them too
		if doc.new_repayment_method == "Repay Fixed Amount per Period":
			# Same EMI, so every skipped installment adds one period at the end
			doc.new_monthly_repayment_amount = self.schedule.monthly_repayment_amount
			doc.new_repayment_period_in_months = completed + earlier_skips + upcoming_count + skip_count
		else:
			# Same maturity, so EMI is recalculated over the installments that remain
			if self.emi_periods() < 1:
				frappe.throw(_("At least one installment must remain after the skipped installments"))
			doc.new_repayment_period_in_months = completed + earlier_skips + upcoming_count


@frappe.whitelist()
def get_upcoming_installments(loan: str, loan_disbursement: str | None = None):
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
		for row in skip.upcoming_rows
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
	frappe.has_permission("Loan", "read", loan, throw=True)

	from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
		process_daily_loan_demands,
	)

	# Demands are generated first, so a failed request must not leave them behind
	frappe.db.savepoint("installment_skip")
	try:
		# Installments due before the skip date must have their demand generated before the schedule is rebuilt.
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
	except Exception:
		frappe.db.rollback(save_point="installment_skip")
		raise

	return restructure.name


def get_skip_date(loan, restructure_date=None):
	"""A restructure cannot start before interest is accrued or before a demand is generated for an installment.
	Both can be ahead of today, e.g. a payroll run for a later period, so start after them."""
	skip_date = getdate(restructure_date or nowdate())
	return max([skip_date, *get_last_accrual_and_demand_dates(loan)])


def get_last_accrual_and_demand_dates(loan):
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
