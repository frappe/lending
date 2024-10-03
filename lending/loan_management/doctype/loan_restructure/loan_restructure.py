# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan.loan import (
	update_all_linked_loan_customer_npa_status,
	update_watch_period_date_for_all_loans,
)
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	make_accrual_interest_entry_for_loans,
)
from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_repayment_schedule.loan_repayment_schedule import (
	get_monthly_repayment_amount,
)


class LoanRestructure(AccountsController):
	def validate(self):
		self.validate_against_initiated_restructure()
		self.validate_restructure_date()
		self.set_completed_tenure()
		self.update_overdue_amounts()
		self.allocate_security_deposit()
		self.validate_waiver_amount()
		self.calculate_balance_amounts()
		self.set_missing_values()
		self.validate_repayment_start_date()
		self.calculate_new_loan_amount()
		self.update_restructured_loan_details()
		if not self.is_new():
			self.make_update_draft_loan_repayment_schedule()

	def validate_against_initiated_restructure(self):
		if frappe.db.exists(
			"Loan Restructure", {"loan": self.loan, "docstatus": 1, "status": "Initiated"}
		):
			frappe.throw(_("Another Loan Restructure is already initiated for this Loan"))

	def validate_restructure_date(self):
		max_due_date = frappe.db.get_value(
			"Loan Interest Accrual", {"loan": self.loan, "docstatus": 1}, "max(posting_date)"
		)
		if max_due_date and getdate(self.restructure_date) < getdate(max_due_date):
			frappe.throw(_("Restructure Date cannot be before last due date {0}").format(max_due_date))

	def after_insert(self):
		self.make_update_draft_loan_repayment_schedule()

	def set_status(self, status=None):
		if self.restructure_type == "Pre Payment":
			self.db_set("status", "Approved")

		if self.docstatus == 1 and self.status not in ("Approved", "Rejected"):
			self.db_set("status", "Initiated")
		elif status:
			self.status = status
			self.db_set("status", status)

	def allocate_security_deposit(self):
		if self.restructure_type == "Normal Restructure":
			deposit_amount = flt(self.available_security_deposit)
			self.principal_adjusted = 0
			self.adjusted_interest_amount = 0
			self.adjusted_other_charges = 0
			self.adjusted_unaccrued_interest = 0

			if deposit_amount > 0:
				# Adjust Principal
				deposit_amount = self.adjust_component(
					deposit_amount, "principal_overdue", "principal_adjusted"
				)

			if deposit_amount > 0:
				# Adjust Interest
				deposit_amount = self.adjust_component(
					deposit_amount, "interest_overdue", "adjusted_interest_amount"
				)

			if deposit_amount > 0:
				# Adjust Penalty
				deposit_amount = self.adjust_component(
					deposit_amount, "penalty_overdue", "adjusted_penalty_amount"
				)

	def calculate_balance_amounts(self):
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		self.balance_principal = flt(
			flt(self.principal_overdue, precision) - flt(self.principal_adjusted, precision), precision
		)

		self.balance_interest_amount = flt(
			flt(self.interest_overdue, precision)
			- flt(self.adjusted_interest_amount, precision)
			- flt(self.interest_waiver_amount, precision),
			precision,
		)

		self.balance_unaccrued_interest = flt(
			flt(self.unaccrued_interest, precision)
			- flt(self.adjusted_unaccrued_interest, precision)
			- flt(self.unaccrued_interest_waiver, precision),
			precision,
		)

		self.balance_penalty_amount = flt(
			flt(self.penalty_overdue) - flt(self.penal_interest_waiver), precision
		)
		self.balance_charges = flt(flt(self.charges_overdue) - flt(self.other_charges_waiver), precision)

	def validate_repayment_start_date(self):
		if getdate(self.repayment_start_date) < getdate(self.restructure_date):
			frappe.throw(_("Restructure Date cannot be after Repayment Start Date"))

	def set_missing_values(self):
		if not self.repayment_start_date:
			self.repayment_start_date = self.restructure_date

		if not self.new_rate_of_interest:
			self.new_rate_of_interest = self.old_rate_of_interest

		if not self.new_repayment_method:
			self.new_repayment_method = self.repayment_method

		if not self.new_repayment_period_in_months:
			self.new_repayment_period_in_months = self.old_tenure

	@frappe.whitelist()
	def set_completed_tenure(self):
		filters = {"loan": self.loan, "docstatus": 1, "status": "Active"}

		if self.loan_disbursement:
			filters["loan_disbursement"] = self.loan_disbursement

		previous_repayment_schedule = frappe.db.get_value("Loan Repayment Schedule", filters, "name")

		self.completed_tenure = frappe.db.count(
			"Repayment Schedule", filters={"parent": previous_repayment_schedule, "demand_generated": 1}
		)

		return self.completed_tenure

	def calculate_new_loan_amount(self):
		self.new_loan_amount = flt(self.pending_principal_amount) - flt(self.principal_adjusted)

		if self.restructure_type == "Normal Restructure":
			if self.treatment_of_normal_interest == "Capitalize":
				self.new_loan_amount += flt(self.balance_interest_amount)

			if self.unaccrued_interest_treatment == "Capitalize":
				self.new_loan_amount += flt(self.balance_unaccrued_interest)

			if (
				self.treatment_of_penal_interest == "Capitalize"
				and self.restructure_type == "Normal Restructure"
			):
				self.new_loan_amount += flt(self.balance_penalty_amount)

			if self.treatment_of_other_charges == "Capitalize":
				self.new_loan_amount += flt(self.balance_charges)

		self.new_loan_amount = flt(self.new_loan_amount, 2)

	def adjust_component(self, amount_to_adjust, component, update_field):
		if amount_to_adjust > 0:
			if amount_to_adjust >= self.get(component):
				old_value = flt(self.get(update_field))
				self.set(update_field, flt(self.get(component)) + old_value)
				amount_to_adjust -= flt(self.get(component))
			else:
				old_value = flt(self.get(update_field))
				self.set(update_field, amount_to_adjust + old_value)
				amount_to_adjust = 0

		return amount_to_adjust

	def on_update_after_submit(self):
		doc_before_save = self.get_doc_before_save()

		if doc_before_save.status != "Initiated":
			return

		self.apply_workflow()

	def apply_workflow(self):
		if self.status == "Approved" and self.docstatus.is_submitted():
			if self.unaccrued_interest and self.restructure_type == "Normal Restructure":
				make_accrual_interest_entry_for_loans(posting_date=self.restructure_date, loan=self.loan)

				# self.make_waiver_and_capitalization_for_penalty()
				self.make_loan_repayment_for_adjustment()
				self.make_loan_repayment_for_waiver()
				# self.make_loan_adjustment_for_capitalization()
				self.make_loan_adjustment_for_carry_forward()

			self.restructure_loan()

			if self.restructure_type == "Normal Restructure":
				self.update_totals()
				self.update_security_deposit_amount()
				self.update_restructure_count()

			self.update_repayment_schedule_status(status="Active")
		elif self.status == "Rejected":
			self.update_repayment_schedule_status(status="Rejected")

	def update_security_deposit_amount(self, cancel=0):
		allocated_amount_details = frappe.db.get_value(
			"Loan Security Deposit",
			{
				"loan": self.loan,
			},
			["name", "allocated_amount"],
			as_dict=1,
		)

		if allocated_amount_details:
			current_allocated_amount = (
				flt(self.principal_adjusted)
				+ flt(self.adjusted_interest_amount)
				+ flt(self.adjusted_unaccrued_interest)
			)

			if cancel:
				current_allocated_amount = -1 * current_allocated_amount

			final_allocated_amount = current_allocated_amount + flt(
				allocated_amount_details.allocated_amount
			)
			frappe.db.set_value(
				"Loan Security Deposit",
				allocated_amount_details.name,
				"allocated_amount",
				final_allocated_amount,
			)

	def update_restructure_count(self, cancel=0):
		if self.restructure_type == "Normal Restructure":
			increment_count = 1
			if cancel:
				increment_count = 0

			frappe.db.set_value(
				"Loan", self.loan, "loan_restructure_count", self.current_restructure_count + increment_count
			)

	def update_repayment_schedule_status(self, status):
		if status == "Initiated":
			draft_schedule = frappe.db.get_value(
				"Loan Repayment Schedule", {"loan_restructure": self.name, "docstatus": 0}, "name"
			)
			schedule = frappe.get_doc("Loan Repayment Schedule", draft_schedule)
			schedule.status = "Initiated"
			schedule.save()
			schedule.submit()
		else:
			frappe.db.set_value(
				"Loan Repayment Schedule", {"loan_restructure": self.name}, "status", status
			)

	def on_submit(self):
		self.validate_new_loan_amount()
		self.set_status()
		self.update_repayment_schedule_status(status="Initiated")
		self.apply_workflow()

	def on_cancel(self):
		self.cancel_repayment_schedule()
		if self.status == "Approved":
			self.update_totals_and_status()
			self.cancel_loan_adjustments()
			self.update_restructure_count(cancel=1)

			if self.restructure_type == "Normal Restructure":
				self.update_security_deposit_amount(cancel=1)

	def update_overdue_amounts(self):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		amounts = calculate_amounts(
			self.loan, self.restructure_date, loan_disbursement=self.loan_disbursement
		)

		self.pending_principal_amount = flt(amounts.get("pending_principal_amount"), precision)
		self.total_overdue_amount = flt(amounts.get("payable_amount"), precision)
		self.principal_overdue = flt(amounts.get("payable_principal_amount"), precision)
		self.interest_overdue = flt(amounts.get("interest_amount"), precision)
		self.penalty_overdue = flt(amounts.get("penalty_amount"), precision)
		self.charges_overdue = flt(amounts.get("total_charges_payable"), precision)
		self.unaccrued_interest = flt(
			flt(amounts.get("unaccrued_interest"), precision)
			+ flt(amounts.get("unbooked_interest"), precision),
			precision,
		)

		if self.unaccrued_interest < 0:
			self.unaccrued_interest = 0

		self.available_security_deposit = flt(amounts.get("available_security_deposit"), precision)

	def cancel_repayment_schedule(self):

		schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan_restructure": self.name, "docstatus": 1}, "name"
		)

		doc = frappe.get_doc("Loan Repayment Schedule", schedule)
		doc.reverse_interest_accruals = 1
		doc.cancel()

	def update_totals_and_status(self):
		if self.restructure_type == "Normal Restructure":
			status = "Restructured"
		else:
			status = "Rescheduled"

		filters = {"docstatus": 1, "loan": self.loan, "status": status}

		if self.loan_disbursement:
			filters["loan_disbursement"] = self.loan_disbursement

		schedule = frappe.db.get_all(
			"Loan Repayment Schedule",
			filters,
			order_by="posting_date desc",
			limit=1,
		)[0]

		frappe.db.set_value("Loan Repayment Schedule", schedule.name, "status", "Active")

	def validate_waiver_amount(self):
		if flt(self.interest_waiver_amount) > flt(self.interest_overdue) - flt(
			self.adjusted_interest_amount
		):
			frappe.throw(_("Interest Waiver Amount cannot be greater than overdue interest"))

		if flt(self.other_charges_waiver) > flt(self.charges_overdue):
			frappe.throw(_("Other Charges Waiver cannot be greater than overdue charges"))

		if flt(self.penal_interest_waiver) > flt(self.penalty_overdue):
			frappe.throw(_("Penalty Waiver cannot be greater than overdue penalty interest"))

		if self.unaccrued_interest_waiver and flt(self.unaccrued_interest_waiver) > flt(
			self.unaccrued_interest
		) - flt(self.adjusted_unaccrued_interest):
			frappe.throw(_("Unaccrued Interest Waiver cannot be greater than overdue amount"))

	def update_restructured_loan_details(self):
		if not self.new_rate_of_interest:
			self.new_rate_of_interest = self.old_rate_of_interest

		if not self.new_repayment_method:
			self.new_repayment_method = frappe.db.get_value("Loan", self.loan, "repayment_method")

		if not self.new_repayment_period_in_months:
			self.new_repayment_period_in_months = frappe.db.get_value(
				"Loan", self.loan, "repayment_periods"
			)

		if self.new_repayment_method == "Repay Over Number of Periods":
			self.new_monthly_repayment_amount = get_monthly_repayment_amount(
				self.new_loan_amount, self.new_rate_of_interest, self.new_repayment_period_in_months, "Monthly"
			)

	def validate_new_loan_amount(self):
		if (
			self.status != "Rejected"
			and self.restructure_type != "Advance Payment"
			and self.new_loan_amount > self.disbursed_amount
		):
			frappe.throw(frappe._("New Loan Amount cannot be greater than original disbursed amount"))

	def restructure_loan(self):
		if self.restructure_type == "Normal Restructure":
			# Mark Loan as NPA
			update_all_linked_loan_customer_npa_status(
				1, self.applicant_type, self.applicant, self.restructure_date, loan=self.loan
			)

			watch_period_days = frappe.db.get_value(
				"Company", self.company, "watch_period_post_loan_restructure_in_days"
			)
			watch_period_end_date = add_days(self.restructure_date, watch_period_days)
			update_watch_period_date_for_all_loans(
				watch_period_end_date, self.applicant_type, self.applicant
			)

			frappe.db.set_value("Loan", self.loan, "days_past_due", 0)
			status = "Restructured"
		else:
			status = "Rescheduled"
		# Mark Old Repayment Schedule as Restructured
		loan_schedule = frappe.qb.DocType("Loan Repayment Schedule")

		query = (
			frappe.qb.update(loan_schedule)
			.set(loan_schedule.status, status)
			.where(
				(loan_schedule.docstatus == 1)
				& (loan_schedule.loan == self.loan)
				& (loan_schedule.status == "Active")
				& (
					(loan_schedule.loan_restructure.isnull())
					| (loan_schedule.loan_restructure == "")
					| (loan_schedule.loan_restructure != self.name)
				)
			)
		)

		if self.loan_disbursement:
			query = query.where(loan_schedule.loan_disbursement == self.loan_disbursement)

		query.run()

	def make_update_draft_loan_repayment_schedule(self):
		adjusted_interest = 0

		if self.treatment_of_normal_interest == "Add To First EMI":
			adjusted_interest += self.balance_interest_amount

		if self.unaccrued_interest_treatment == "Add To First EMI":
			adjusted_interest += self.balance_unaccrued_interest

		draft_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan_restructure": self.name, "docstatus": 0}, "name"
		)
		if draft_schedule:
			schedule = frappe.get_doc("Loan Repayment Schedule", draft_schedule)
			schedule.update(self.get_schedule_details(adjusted_interest))
			schedule.save()
		else:
			schedule = frappe.new_doc("Loan Repayment Schedule")
			schedule_details = self.get_schedule_details(adjusted_interest)
			schedule.update(schedule_details)
			schedule.insert()

	def get_schedule_details(self, adjusted_interest=0):
		return {
			"loan": self.loan,
			"loan_restructure": self.name,
			"repayment_method": self.new_repayment_method,
			"repayment_start_date": self.repayment_start_date,
			"repayment_periods": self.new_repayment_period_in_months,
			"monthly_repayment_amount": self.new_monthly_repayment_amount,
			"rate_of_interest": self.new_rate_of_interest,
			"loan_amount": self.new_loan_amount,
			"current_principal_amount": self.new_loan_amount,
			"posting_date": self.restructure_date,
			"repayment_frequency": "Monthly",
			"adjusted_interest": adjusted_interest if self.restructure_type == "Normal Restructure" else 0,
			"restructure_type": self.restructure_type,
			"loan_disbursement": self.loan_disbursement,
		}

	def update_totals(self, cancel=0):
		total_payment = 0
		total_interest_payable = 0

		if not cancel:
			filters = {"loan_restructure": self.name, "docstatus": 1, "status": "Initiated"}
		else:
			filters = {"docstatus": 1, "status": "Active"}

		schedule = frappe.get_doc("Loan Repayment Schedule", filters)

		for data in schedule.repayment_schedule:
			total_payment += data.total_payment
			total_interest_payable += data.interest_amount

		total_principal_paid = 0
		total_amount_paid = 0
		loan_amount = self.new_loan_amount
		monthly_repayment_amount = schedule.monthly_repayment_amount

		if cancel:
			total_principal_paid = self.total_principal_paid
			total_amount_paid = self.total_amount_paid
			loan_amount = self.disbursed_amount
			monthly_repayment_amount = self.old_emi

		frappe.db.set_value(
			"Loan",
			self.loan,
			{
				"loan_amount": loan_amount,
				"rate_of_interest": self.new_rate_of_interest,
				"monthly_repayment_amount": monthly_repayment_amount,
				"total_payment": total_payment,
				"total_interest_payable": total_interest_payable,
				"total_principal_paid": total_principal_paid,
				"total_amount_paid": total_amount_paid,
				"repayment_periods": self.new_repayment_period_in_months,
				"tenure_post_restructure": self.new_repayment_period_in_months + self.completed_tenure,
			},
		)

	def make_waiver_and_capitalization_for_penalty(self):
		if self.penal_interest_waiver:
			create_loan_repayment(
				self.loan, self.restructure_date, "Penalty Waiver", self.penal_interest_waiver, self.name
			)

		if self.balance_penalty_amount and self.treatment_of_penal_interest == "Capitalize":
			create_loan_repayment(
				self.loan,
				self.restructure_date,
				"Penalty Capitalization",
				self.balance_penalty_amount,
				self.name,
			)

	def make_loan_repayment_for_adjustment(self):
		if self.principal_adjusted:
			create_loan_repayment(
				self.loan, self.restructure_date, "Principal Adjustment", self.principal_adjusted, self.name
			)

		if self.adjusted_interest_amount:
			create_loan_repayment(
				self.loan,
				self.restructure_date,
				"Interest Adjustment",
				self.adjusted_interest_amount,
				self.name,
			)

	def make_loan_repayment_for_waiver(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand

		if self.interest_waiver_amount:
			create_loan_repayment(
				self.loan, self.restructure_date, "Interest Waiver", self.interest_waiver_amount, self.name
			)

		if self.unaccrued_interest_waiver:
			create_loan_demand(
				self.loan,
				self.restructure_date,
				"EMI",
				"Interest",
				self.unaccrued_interest_waiver,
			)

			create_loan_repayment(
				self.loan, self.restructure_date, "Interest Waiver", self.unaccrued_interest_waiver, self.name
			)

		if self.other_charges_waiver:
			create_loan_repayment(
				self.loan, self.restructure_date, "Charges Waiver", self.other_charges_waiver, self.name
			)

	def cancel_loan_adjustments(self):
		for d in frappe.get_all("Loan Repayment", {"loan_restructure": self.name}):
			doc = frappe.get_doc("Loan Repayment", d.name)
			doc.cancel()

	def make_loan_adjustment_for_capitalization(self):
		if self.balance_interest_amount and self.treatment_of_normal_interest == "Capitalize":
			create_loan_repayment(
				self.loan,
				self.restructure_date,
				"Interest Capitalization",
				self.balance_interest_amount,
				self.name,
			)

		if self.balance_unaccrued_interest and self.unaccrued_interest_treatment == "Capitalize":
			create_loan_repayment(
				self.loan,
				self.restructure_date,
				"Interest Capitalization",
				self.balance_unaccrued_interest,
				self.name,
			)

		if self.balance_charges and self.treatment_of_other_charges == "Capitalize":
			create_loan_repayment(
				self.loan,
				self.restructure_date,
				"Charges Capitalization",
				self.balance_charges,
				self.name,
			)

		if self.balance_principal:
			create_loan_repayment(
				self.loan,
				self.restructure_date,
				"Principal Capitalization",
				self.balance_principal,
				self.name,
			)

	def make_loan_adjustment_for_carry_forward(self):
		if self.restructure_type == "Normal Restructure":
			if self.balance_interest_amount and self.treatment_of_normal_interest == "Add To First EMI":
				create_loan_repayment(
					self.loan,
					self.restructure_date,
					"Interest Carry Forward",
					self.balance_interest_amount,
					self.name,
				)

			if self.balance_unaccrued_interest and self.unaccrued_interest_treatment == "Add To First EMI":
				create_loan_repayment(
					self.loan,
					self.restructure_date,
					"Interest Carry Forward",
					self.balance_unaccrued_interest,
					self.name,
				)


def create_loan_repayment(
	loan,
	posting_date,
	repayment_type,
	waiver_amount,
	adjustment_name=None,
	restructure_name=None,
	is_write_off_waiver=0,
	payment_account=None,
):
	repayment = frappe.new_doc("Loan Repayment")
	repayment.offset_based_on_npa = 1
	repayment.against_loan = loan
	repayment.posting_date = posting_date
	repayment.repayment_type = repayment_type
	repayment.amount_paid = waiver_amount
	repayment.loan_adjustment = adjustment_name
	repayment.loan_restructure = restructure_name
	repayment.is_write_off_waiver = is_write_off_waiver
	repayment.payment_account = payment_account
	repayment.save()
	repayment.submit()


def create_update_loan_reschedule(
	loan, posting_date, loan_repayment, repayment_type, principal_adjusted, loan_disbursement=None
):
	if frappe.db.get_value("Loan Restructure", {"loan_repayment": loan_repayment}):
		loan_restructure = frappe.get_doc("Loan Restructure", {"loan_repayment": loan_repayment})
	else:
		loan_restructure = frappe.new_doc("Loan Restructure")
		loan_restructure.loan_repayment = loan_repayment

	loan_restructure.update(
		get_restructure_details(
			loan, posting_date, repayment_type, principal_adjusted, loan_disbursement=loan_disbursement
		)
	)

	loan_restructure.save()


def get_restructure_details(
	loan, posting_date, repayment_type, principal_adjusted, loan_disbursement=None
):
	(
		pending_tenure,
		monthly_repayment_amount,
		repayment_start_date,
	) = get_pending_tenure_and_start_date(
		loan, posting_date, repayment_type, loan_disbursement=loan_disbursement
	)

	loan_restructure = {
		"loan": loan,
		"restructure_type": repayment_type,
		"restructure_date": posting_date,
		"repayment_start_date": repayment_start_date,
		"principal_adjusted": principal_adjusted,
		"loan_disbursement": loan_disbursement,
	}

	if repayment_type == "Advance Payment":
		loan_restructure["new_repayment_method"] = "Repay Over Number of Periods"
		loan_restructure["new_repayment_period_in_months"] = pending_tenure
	else:
		loan_restructure["new_repayment_method"] = "Repay Fixed Amount per Period"
		loan_restructure["new_monthly_repayment_amount"] = monthly_repayment_amount
		loan_restructure["new_repayment_period_in_months"] = pending_tenure

	return loan_restructure


def get_pending_tenure_and_start_date(loan, posting_date, repayment_type, loan_disbursement=None):
	from lending.loan_management.doctype.loan.loan import get_cyclic_date

	ignore_bpi = False

	filters = {"loan": loan, "docstatus": 1, "status": "Active"}
	if loan_disbursement:
		filters["loan_disbursement"] = loan_disbursement

	(
		prev_tenure,
		monthly_repayment_amount,
		repayment_frequency,
		prev_repayment_start_date,
	) = frappe.db.get_value(
		"Loan Repayment Schedule",
		filters,
		["repayment_periods", "monthly_repayment_amount", "repayment_frequency", "repayment_start_date"],
	)

	loan_product = frappe.db.get_value("Loan", loan, "loan_product")

	if repayment_frequency == "One Time":
		repayment_start_date = prev_repayment_start_date
	else:
		if repayment_type == "Pre Payment":
			ignore_bpi = True

		repayment_start_date = get_cyclic_date(loan_product, posting_date, ignore_bpi=ignore_bpi)

	return prev_tenure, monthly_repayment_amount, repayment_start_date
