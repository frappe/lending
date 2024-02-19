# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import cint, flt, getdate

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_repayment.loan_repayment import update_installment_counts


class LoanDemand(AccountsController):
	def validate(self):
		self.outstanding_amount = flt(self.demand_amount) - flt(self.paid_amount)

	def on_submit(self):
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			get_last_accrual_date,
		)
		from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
			process_loan_interest_accrual_for_loans,
		)

		if self.demand_subtype in ("Principal", "Interest", "Penalty"):
			self.make_gl_entries()

		if self.demand_type == "EMI":
			self.update_repayment_schedule()

		last_accrual_job_date = get_last_accrual_date(self.loan, self.demand_date, "Normal Interest")

		if getdate(last_accrual_job_date) < getdate(self.demand_date):
			process_loan_interest_accrual_for_loans(posting_date=self.demand_date, loan=self.loan)

	def update_repayment_schedule(self, cancel=0):
		if self.repayment_schedule_detail:
			frappe.db.set_value(
				"Repayment Schedule", self.repayment_schedule_detail, "demand_generated", cint(not cancel)
			)

	def on_cancel(self):
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		self.make_gl_entries(cancel=1)
		self.update_repayment_schedule(cancel=1)

	def make_gl_entries(self, cancel=0):
		gl_entries = []

		if self.demand_subtype == "Principal":
			return

		if self.demand_type == "Charges":
			return

		if self.demand_subtype == "Interest":
			accrual_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "interest_accrued_account"
			)
			receivable_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "interest_receivable_account"
			)
		elif self.demand_subtype == "Penalty":
			accrual_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "penalty_accrued_account"
			)
			receivable_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "penalty_receivable_account"
			)

		gl_entries.append(
			self.get_gl_dict(
				{
					"posting_date": self.demand_date,
					"account": receivable_account,
					"against": self.loan,
					"debit": self.demand_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.loan,
					"party_type": self.applicant_type,
					"party": self.applicant,
					"cost_center": self.cost_center,
				}
			)
		)

		gl_entries.append(
			self.get_gl_dict(
				{
					"posting_date": self.demand_date,
					"account": accrual_account,
					"against": receivable_account,
					"credit": self.demand_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.loan,
					"cost_center": self.cost_center,
				}
			)
		)

		make_gl_entries(gl_entries, cancel=cancel, adv_adj=0)


def make_loan_demand_for_term_loans(
	posting_date, loan_product=None, loan=None, process_loan_demand=None
):
	filters = {
		"docstatus": 1,
		"status": ("in", ("Disbursed", "Partially Disbursed", "Active")),
		"is_term_loan": 1,
		"freeze_account": 0,
	}

	if loan_product:
		filters["loan_product"] = loan_product

	if loan:
		filters["name"] = loan

	open_loans = frappe.db.get_all("Loan", filters=filters, pluck="name")

	loan_repayment_schedules = frappe.db.get_all(
		"Loan Repayment Schedule",
		filters={"docstatus": 1, "status": "Active", "loan": ("in", open_loans)},
		fields=["name", "loan", "loan_disbursement"],
	)

	loan_repayment_schedule_map = frappe._dict()
	disbursement_map = frappe._dict()

	for schedule in loan_repayment_schedules:
		loan_repayment_schedule_map[schedule.name] = schedule.loan
		disbursement_map[schedule.name] = schedule.loan_disbursement

	repayment_schedules = loan_repayment_schedule_map.keys()

	emi_rows = frappe.db.get_all(
		"Repayment Schedule",
		filters={
			"parent": ("in", repayment_schedules),
			"payment_date": ("<=", posting_date),
			"demand_generated": 0,
		},
		fields=["name", "parent", "principal_amount", "interest_amount", "payment_date"],
	)

	for row in emi_rows:
		demand_type = "EMI"
		create_loan_demand(
			loan_repayment_schedule_map.get(row.parent),
			row.payment_date,
			demand_type,
			"Interest",
			row.interest_amount,
			loan_repayment_schedule=row.parent,
			loan_disbursement=disbursement_map.get(row.parent),
			repayment_schedule_detail=row.name,
			process_loan_demand=process_loan_demand,
		)

		create_loan_demand(
			loan_repayment_schedule_map.get(row.parent),
			row.payment_date,
			demand_type,
			"Principal",
			row.principal_amount,
			loan_repayment_schedule=row.parent,
			loan_disbursement=disbursement_map.get(row.parent),
			repayment_schedule_detail=row.name,
			process_loan_demand=process_loan_demand,
		)

		update_installment_counts(loan_repayment_schedule_map.get(row.parent))


def create_loan_demand(
	loan,
	posting_date,
	demand_type,
	demand_subtype,
	amount,
	loan_repayment_schedule=None,
	loan_disbursement=None,
	repayment_schedule_detail=None,
	sales_invoice=None,
	process_loan_demand=None,
	paid_amount=0,
):
	if amount:
		demand = frappe.new_doc("Loan Demand")
		demand.loan = loan
		demand.loan_repayment_schedule = loan_repayment_schedule
		demand.loan_disbursement = loan_disbursement
		demand.repayment_schedule_detail = repayment_schedule_detail
		demand.demand_date = posting_date
		demand.demand_type = demand_type
		demand.demand_subtype = demand_subtype
		demand.demand_amount = amount
		demand.sales_invoice = sales_invoice
		demand.process_loan_demand = process_loan_demand
		demand.paid_amount = paid_amount
		demand.save()
		demand.submit()


def reverse_demands(loan, posting_date):
	for demand in frappe.get_all("Loan Demand", {"loan": loan, "demand_date": (">", posting_date)}):
		frappe.get_doc("Loan Demand", demand.name).cancel()
