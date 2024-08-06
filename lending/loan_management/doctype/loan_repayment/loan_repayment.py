# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.query_builder.functions import Round, Sum
from frappe.utils import cint, flt, get_datetime, getdate

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_limit_change_log.loan_limit_change_log import (
	create_loan_limit_change_log,
)
from lending.loan_management.doctype.loan_security_assignment.loan_security_assignment import (
	update_loan_securities_values,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)


class LoanRepayment(AccountsController):
	def before_validate(self):
		self.set_repayment_account()

	def validate(self):
		charges = None
		if self.get("payable_charges"):
			charges = [d.get("charge_code") for d in self.get("payable_charges")]

		amounts = calculate_amounts(
			self.against_loan, self.posting_date, payment_type=self.repayment_type, charges=charges
		)
		self.set_missing_values(amounts)
		self.check_future_entries()
		self.validate_security_deposit_amount()
		self.validate_repayment_type()
		self.validate_amount(amounts)
		self.allocate_amount_against_demands(amounts)

	def on_update(self):
		from lending.loan_management.doctype.loan_restructure.loan_restructure import (
			create_update_loan_reschedule,
		)

		excess_amount = self.principal_amount_paid - self.pending_principal_amount

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		if self.repayment_type in ("Advance Payment", "Pre Payment") and excess_amount < 0:
			if flt(self.amount_paid, precision) > flt(self.payable_amount, precision):
				create_update_loan_reschedule(
					self.against_loan,
					self.posting_date,
					self.name,
					self.repayment_type,
					self.principal_amount_paid,
				)

	def on_submit(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import reverse_demands
		from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
			make_sales_invoice_for_charge,
		)
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)
		from lending.loan_management.doctype.loan_restructure.loan_restructure import (
			create_update_loan_reschedule,
		)
		from lending.loan_management.doctype.loan_write_off.loan_write_off import (
			write_off_suspense_entries,
		)
		from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
			create_process_loan_classification,
		)
		from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
			process_loan_interest_accrual_for_loans,
		)

		make_sales_invoice_for_charge(
			self.against_loan,
			"loan_repayment",
			self.name,
			self.posting_date,
			self.company,
			self.get("prepayment_charges"),
		)

		if not self.principal_amount_paid >= self.pending_principal_amount:
			if not self.is_term_loan or self.repayment_type in ("Advance Payment", "Pre Payment"):
				amounts = calculate_amounts(
					self.against_loan, self.posting_date, payment_type=self.repayment_type
				)
				self.allocate_amount_against_demands(amounts, on_submit=True)
				self.db_update_all()

				create_update_loan_reschedule(
					self.against_loan,
					self.posting_date,
					self.name,
					self.repayment_type,
					self.principal_amount_paid,
				)

			if self.repayment_type in ("Advance Payment", "Pre Payment"):
				self.process_reschedule()

		if self.unbooked_interest_paid and self.principal_amount_paid >= self.pending_principal_amount:
			self.book_interest_accrued_not_demanded()

		if self.repayment_type in ("Write Off Settlement", "Full Settlement"):
			self.post_write_off_settlements()

		self.update_paid_amounts()
		self.update_demands()
		self.update_limits()
		self.update_security_deposit_amount()
		update_installment_counts(self.against_loan)

		update_loan_securities_values(self.against_loan, self.principal_amount_paid, self.doctype)
		self.create_loan_limit_change_log()
		self.make_credit_note_for_charge_waivers()
		self.make_gl_entries()

		if self.is_npa and self.repayment_type not in (
			"Interest Waiver",
			"Penalty Waiver",
			"Charges Waiver",
		):
			write_off_suspense_entries(
				self.against_loan,
				self.loan_product,
				self.posting_date,
				self.company,
				interest_amount=self.total_interest_paid,
				penalty_amount=self.total_penalty_paid,
			)

		if self.is_term_loan:
			reverse_loan_interest_accruals(
				self.against_loan, self.posting_date, interest_type="Penal Interest"
			)
			reverse_demands(self.against_loan, self.posting_date, demand_type="Penalty")

			create_process_loan_classification(
				posting_date=self.posting_date,
				loan_product=self.loan_product,
				loan=self.against_loan,
				payment_reference=self.name,
			)

		if not self.is_term_loan:
			process_loan_interest_accrual_for_loans(
				posting_date=self.posting_date, loan=self.against_loan, loan_product=self.loan_product
			)

	def process_reschedule(self):
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)

		reverse_loan_interest_accruals(self.against_loan, self.posting_date)
		loan_restructure = frappe.get_doc("Loan Restructure", {"loan_repayment": self.name})
		loan_restructure.flags.ignore_links = True
		loan_restructure.status = "Approved"
		loan_restructure.submit()

	def set_repayment_account(self):
		if not self.payment_account and self.mode_of_payment:
			self.payment_account = frappe.db.get_value(
				"Mode of Payment Account",
				{"parent": self.mode_of_payment, "company": self.company},
				"default_account",
			)

		if not self.payment_account and self.bank_account:
			self.payment_account = frappe.db.get_value("Bank Account", self.bank_account, "account")

		if not self.payment_account:
			self.payment_account = frappe.db.get_value("Loan Product", self.loan_product, "payment_account")

	def make_credit_note_for_charge_waivers(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import make_credit_note

		if self.repayment_type == "Charges Waiver":
			for demand in self.get("repayment_details"):
				demand_doc = frappe.get_doc("Loan Demand", demand.loan_demand)
				waiver_account = self.get_charges_waiver_account(self.loan_product, demand.demand_subtype)
				make_credit_note(
					demand_doc.company,
					demand_doc.demand_subtype,
					demand_doc.applicant,
					demand_doc.loan,
					demand_doc.sales_invoice,
					self.posting_date,
					amount=demand.paid_amount,
					loan_repayment=self.name,
					waiver_account=waiver_account,
				)

	def create_loan_limit_change_log(self):
		create_loan_limit_change_log(
			loan=self.against_loan,
			event="Repayment",
			change_date=self.posting_date,
			value_type="Available Limit Amount",
			value_change=self.principal_amount_paid,
		)

	def on_cancel(self):
		self.check_future_accruals()
		self.mark_as_unpaid()
		self.update_demands(cancel=1)
		self.update_limits(cancel=1)
		self.update_security_deposit_amount(cancel=1)

		frappe.db.set_value("Loan", self.against_loan, "days_past_due", self.days_past_due)

		self.cancel_charge_demands()

		if self.repayment_type in ("Advance Payment", "Pre Payment"):
			self.cancel_loan_restructure()

		update_loan_securities_values(
			self.against_loan,
			self.principal_amount_paid,
			self.doctype,
			on_trigger_doc_cancel=1,
		)

		self.ignore_linked_doctypes = [
			"GL Entry",
			"Payment Ledger Entry",
			"Process Loan Classification",
			"Sales Invoice",
			"Loan Repayment Schedule",
		]
		self.make_gl_entries(cancel=1)
		update_installment_counts(self.against_loan)

	def cancel_charge_demands(self):
		sales_invoice = frappe.db.get_value("Sales Invoice", {"loan_repayment": self.name})
		loan_demands = frappe.db.get_all("Loan Demand", {"sales_invoice": sales_invoice}, pluck="name")
		for demand in loan_demands:
			frappe.get_doc("Loan Demand", demand).cancel()

	def cancel_loan_restructure(self):
		loan_restructure = frappe.db.get_value(
			"Loan Restructure", {"loan_repayment": self.name, "docstatus": 1}
		)
		if loan_restructure:
			frappe.get_doc("Loan Restructure", {"loan_repayment": self.name}).cancel()

	def set_missing_values(self, amounts):
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		if not self.posting_date:
			self.posting_date = get_datetime()

		if not self.cost_center:
			self.cost_center = erpnext.get_default_cost_center(self.company)

		if not self.interest_payable:
			self.interest_payable = flt(amounts["interest_amount"], precision)

		if not self.penalty_amount:
			self.penalty_amount = flt(amounts["penalty_amount"], precision)

		if not self.pending_principal_amount:
			self.pending_principal_amount = flt(amounts["pending_principal_amount"], precision)

		if not self.payable_principal_amount and self.is_term_loan:
			self.payable_principal_amount = flt(amounts["payable_principal_amount"], precision)

		if not self.payable_amount:
			self.payable_amount = flt(amounts["payable_amount"], precision)

		shortfall_amount = flt(
			frappe.db.get_value(
				"Loan Security Shortfall", {"loan": self.against_loan, "status": "Pending"}, "shortfall_amount"
			)
		)

		if shortfall_amount:
			self.shortfall_amount = shortfall_amount

		if amounts.get("due_date"):
			self.due_date = amounts.get("due_date")

		if hasattr(self, "repay_from_salary") and hasattr(self, "payroll_payable_account"):
			if self.repay_from_salary and not self.payroll_payable_account:
				frappe.throw(_("Please set Payroll Payable Account in Loan Repayment"))
			elif not self.repay_from_salary and self.payroll_payable_account:
				self.repay_from_salary = 1

	def check_future_entries(self):
		future_repayment_date = frappe.db.get_value(
			"Loan Repayment",
			{"posting_date": (">", self.posting_date), "docstatus": 1, "against_loan": self.against_loan},
			"posting_date",
		)

		if future_repayment_date:
			frappe.throw("Repayment already made till date {0}".format(get_datetime(future_repayment_date)))

	def validate_security_deposit_amount(self):
		if self.repayment_type == "Security Deposit Adjustment":
			available_deposit = frappe.db.get_value(
				"Loan Security Deposit",
				{"loan": self.against_loan, "docstatus": 1},
				"available_amount",
			)

			if flt(self.amount_paid) > flt(available_deposit):
				frappe.throw(_("Amount paid cannot be greater than available security deposit"))

	def validate_repayment_type(self):
		loan_status = frappe.db.get_value("Loan", self.against_loan, "status")
		if loan_status == "Written Off":
			if (
				self.repayment_type not in ("Write Off Recovery", "Write Off Settlement")
				and not self.is_write_off_waiver
			):
				frappe.throw(_("Repayment type can only be Write Off Recovery or Write Off Settlement"))
		else:
			if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
				frappe.throw(_("Incorrect repayment type, please write off the loan first"))

	def validate_amount(self, amounts):
		if not self.amount_paid:
			frappe.throw(_("Amount paid cannot be zero"))

		if self.repayment_type == "Loan Closure":
			auto_write_off_amount = frappe.db.get_value(
				"Loan Product", self.loan_product, "write_off_amount"
			)

			if flt(self.amount_paid) < (flt(amounts.get("payable_amount")) - flt(auto_write_off_amount)):
				frappe.throw(_("Amount paid cannot be less than payable amount for loan closure"))

		if (
			self.repayment_type in ("Interest Waiver", "Penalty Waiver", "Charges Waiver")
			and not self.is_write_off_waiver
		):
			precision = cint(frappe.db.get_default("currency_precision")) or 2
			payable_amount = self.get_waiver_amount(amounts)

			if flt(self.amount_paid, precision) > flt(payable_amount, precision):
				frappe.throw(
					_("Waived {0} amount cannot be greater than overdue amount").format(
						{
							"Interest Waiver": "interest",
							"Penalty Waiver": "penalty",
							"Charges Waiver": "charges",
						}.get(self.repayment_type)
					)
				)

	def get_waiver_amount(self, amounts):
		if self.repayment_type == "Interest Waiver":
			return (
				amounts.get("interest_amount", 0)
				+ amounts.get("unaccrued_interest", 0)
				+ amounts.get("unbooked_interest", 0)
			)
		elif self.repayment_type == "Penalty Waiver":
			return amounts.get("penalty_amount", 0) + amounts.get("unbooked_penalty", 0)
		elif self.repayment_type == "Charges Waiver":
			return amounts.get("payable_amount", 0)

	def book_interest_accrued_not_demanded(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		if flt(self.unbooked_interest_paid, precision) > 0:
			create_loan_demand(
				self.against_loan,
				self.posting_date,
				"EMI",
				"Interest",
				flt(self.unbooked_interest_paid, precision),
				paid_amount=self.unbooked_interest_paid,
			)

		if flt(self.unbooked_penalty_paid, precision) > 0:
			create_loan_demand(
				self.against_loan,
				self.posting_date,
				"Penalty",
				"Penalty",
				flt(self.unbooked_penalty_paid, precision),
				paid_amount=self.unbooked_penalty_paid,
			)

	def update_paid_amounts(self):
		loan = frappe.qb.DocType("Loan")
		query = (
			frappe.qb.update(loan)
			.set(loan.total_amount_paid, loan.total_amount_paid + self.amount_paid)
			.set(loan.total_principal_paid, loan.total_principal_paid + self.principal_amount_paid)
			.where(loan.name == self.against_loan)
		)

		if flt(self.excess_amount) > 0:
			query = query.set(loan.excess_amount_paid, loan.excess_amount_paid + self.excess_amount)

		if self.repayment_type == "Write Off Settlement":
			auto_write_off_amount = flt(
				frappe.db.get_value("Loan Product", self.loan_product, "write_off_amount")
			)
			if self.amount_paid >= self.payable_amount - auto_write_off_amount:
				query = query.set(loan.status, "Closed")
			else:
				query = query.set(loan.status, "Settled")

		elif self.auto_close_loan() and self.repayment_type in (
			"Normal Repayment",
			"Pre Payment",
			"Advance Payment",
		):
			query = query.set(loan.status, "Closed")
		elif self.repayment_type == "Full Settlement":
			query = query.set(loan.status, "Settled")

		query.run()

		update_shortfall_status(self.against_loan, self.principal_amount_paid)

	def post_write_off_settlements(self):
		from lending.loan_management.doctype.loan_restructure.loan_restructure import (
			create_loan_repayment,
		)

		if self.interest_payable - self.total_interest_paid > 0:
			interest_amount = self.interest_payable - self.total_interest_paid
			create_loan_repayment(
				self.against_loan,
				self.posting_date,
				"Interest Waiver",
				interest_amount,
				is_write_off_waiver=1,
			)

		if self.penalty_amount - self.total_penalty_paid > 0:
			penalty_amount = self.penalty_amount - self.total_penalty_paid
			create_loan_repayment(
				self.against_loan,
				self.posting_date,
				"Penalty Waiver",
				penalty_amount,
				is_write_off_waiver=1,
			)

		if (
			self.payable_principal_amount - self.principal_amount_paid > 0
			and self.repayment_type == "Full Settlement"
		):
			principal_amount = self.payable_principal_amount - self.principal_amount_paid
			loan_write_off_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "write_off_account"
			)
			create_loan_repayment(
				self.against_loan,
				self.posting_date,
				"Principal Adjustment",
				principal_amount,
				payment_account=loan_write_off_account,
			)

	def auto_close_loan(self):
		auto_close = False

		auto_write_off_amount, excess_amount_limit = frappe.db.get_value(
			"Loan Product", self.loan_product, ["write_off_amount", "excess_amount_acceptance_limit"]
		)

		shortfall_amount = self.pending_principal_amount - self.principal_amount_paid

		if shortfall_amount > 0 and shortfall_amount <= auto_write_off_amount:
			auto_close = True

		excess_amount = self.principal_amount_paid - self.pending_principal_amount
		if excess_amount > 0 and excess_amount <= excess_amount_limit:
			auto_close = True

		if (
			self.principal_amount_paid >= self.pending_principal_amount
			and not flt(shortfall_amount)
			and flt(self.excess_amount) <= excess_amount_limit
		):
			auto_close = True

		return auto_close

	def mark_as_unpaid(self):
		if self.repayment_type in (
			"Normal Repayment",
			"Pre Payment",
			"Advance Payment",
			"Loan Closure",
			"Full Settlement",
			"Write Off Settlement",
			"Partial Settlement",
			"Principal Adjustment",
		):
			loan = frappe.qb.DocType("Loan")

			loan_status, repayment_schedule_type = frappe.db.get_value(
				"Loan", self.against_loan, ["status", "repayment_schedule_type"]
			)

			query = (
				frappe.qb.update(loan)
				.set(loan.total_amount_paid, loan.total_amount_paid - self.amount_paid)
				.set(loan.total_principal_paid, loan.total_principal_paid - self.principal_amount_paid)
				.where(loan.name == self.against_loan)
			)

			if self.repayment_type == "Write Off Settlement":
				query = query.set(loan.status, "Written Off")
			elif self.repayment_type == "Full Settlement":
				query = query.set(loan.status, "Disbursed")
			elif loan_status == "Closed":
				if repayment_schedule_type == "Line of Credit":
					query = query.set(loan.status, "Active")
				else:
					query = query.set(loan.status, "Disbursed")

			if self.excess_amount:
				query = query.set(loan.excess_amount_paid, loan.excess_amount_paid - self.excess_amount)

			query.run()

	def update_demands(self, cancel=0):
		loan_demand = frappe.qb.DocType("Loan Demand")
		for payment in self.repayment_details:
			paid_amount = payment.paid_amount

			if cancel:
				paid_amount = -1 * flt(payment.paid_amount)

			if self.repayment_type in ("Interest Waiver", "Penalty Waiver", "Charges Waiver"):
				paid_amount_field = "waived_amount"
			else:
				paid_amount_field = "paid_amount"

			frappe.qb.update(loan_demand).set(
				loan_demand[paid_amount_field], loan_demand[paid_amount_field] + paid_amount
			).set(
				loan_demand.outstanding_amount, loan_demand.outstanding_amount - paid_amount
			).where(
				loan_demand.name == payment.loan_demand
			).run()

	def update_limits(self, cancel=0):
		principal_amount_paid = self.principal_amount_paid
		if cancel:
			principal_amount_paid = -1 * flt(self.principal_amount_paid)

		loan = frappe.qb.DocType("Loan")

		if self.repayment_schedule_type == "Line of Credit":
			frappe.qb.update(loan).set(
				loan.available_limit_amount, loan.available_limit_amount + principal_amount_paid
			).set(
				loan.utilized_limit_amount, loan.utilized_limit_amount - principal_amount_paid
			).where(
				loan.name == self.against_loan
			).run()

	def update_security_deposit_amount(self, cancel=0):
		if self.repayment_type == "Security Deposit Adjustment":
			loan_security_deposit = frappe.qb.DocType("Loan Security Deposit")
			if cancel:
				amount = -1 * flt(self.amount_paid)
			else:
				amount = flt(self.amount_paid)

			frappe.qb.update(loan_security_deposit).set(
				loan_security_deposit.available_amount, loan_security_deposit.available_amount - amount
			).set(
				loan_security_deposit.allocated_amount, loan_security_deposit.allocated_amount + amount
			).where(
				loan_security_deposit.loan == self.against_loan
			).run()

	def check_future_accruals(self):
		future_repayment = frappe.db.get_value(
			"Loan Repayment",
			{"posting_date": (">", self.posting_date), "docstatus": 1, "against_loan": self.against_loan},
			"posting_date",
		)

		if future_repayment:
			frappe.throw(
				"Cannot cancel. Repayments made till date {0}".format(get_datetime(future_repayment))
			)

	def allocate_amount_against_demands(self, amounts, on_submit=False):
		from lending.loan_management.doctype.loan_write_off.loan_write_off import (
			get_accrued_interest_for_write_off_recovery,
			get_write_off_recovery_details,
			get_write_off_waivers,
		)

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		loan_status = frappe.db.get_value("Loan", self.against_loan, "status")

		if not on_submit:
			self.set("repayment_details", [])
		else:
			records_to_delete = [d.name for d in self.get("repayment_details")]
			lr_detail = frappe.qb.DocType("Loan Repayment Detail")
			if records_to_delete:
				frappe.qb.from_(lr_detail).delete().where(lr_detail.name.isin(records_to_delete)).run()
				self.load_from_db()

		self.principal_amount_paid = 0
		self.total_penalty_paid = 0
		self.total_interest_paid = 0
		self.total_charges_paid = 0
		self.unbooked_interest_paid = 0
		self.unbooked_penalty_paid = 0

		if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
			waiver_details = get_write_off_waivers(self.against_loan, self.posting_date)
			recovery_details = get_write_off_recovery_details(self.against_loan, self.posting_date)
			pending_interest = flt(waiver_details.get("Interest Waiver")) - flt(
				recovery_details.get("total_interest")
			)
			pending_penalty = flt(waiver_details.get("Penalty Waiver")) - flt(
				recovery_details.get("total_penalty")
			)

			accrued_interest, accrued_penalty = get_accrued_interest_for_write_off_recovery(
				self.against_loan, self.posting_date
			)

			if pending_interest > 0:
				amounts["unbooked_interest"] = pending_interest

			if pending_penalty > 0:
				amounts["unbooked_penalty"] = pending_penalty

			if accrued_interest > 0:
				amounts["unbooked_interest"] += accrued_interest

			if accrued_penalty > 0:
				amounts["unbooked_penalty"] += accrued_penalty

			self.interest_payable = amounts.get("unbooked_interest")
			self.penalty_amount = amounts.get("unbooked_penalty")

			self.payable_amount = (
				self.pending_principal_amount + self.interest_payable + self.penalty_amount
			)

		amount_paid = self.amount_paid

		if self.repayment_type == "Charge Payment":
			amount_paid = self.allocate_charges(amount_paid, amounts.get("unpaid_demands"))
		else:
			if loan_status == "Written Off":
				allocation_order = frappe.db.get_value(
					"Company", self.company, "collection_offset_sequence_for_written_off_asset"
				)
			elif self.repayment_type in ("Partial Settlement", "Full Settlement", "Principal Adjustment"):
				allocation_order = frappe.db.get_value(
					"Company", self.company, "collection_offset_sequence_for_settlement_collection"
				)
			elif self.is_npa:
				allocation_order = frappe.db.get_value(
					"Company", self.company, "collection_offset_sequence_for_sub_standard_asset"
				)
			else:
				allocation_order = frappe.db.get_value(
					"Company", self.company, "collection_offset_sequence_for_standard_asset"
				)

			if self.shortfall_amount and self.amount_paid > self.shortfall_amount:
				self.principal_amount_paid = self.shortfall_amount
			elif self.shortfall_amount:
				self.principal_amount_paid = self.amount_paid

			amount_paid = self.apply_allocation_order(
				allocation_order, amount_paid, amounts.get("unpaid_demands")
			)

		for payment in self.repayment_details:
			if payment.demand_subtype == "Interest":
				self.total_interest_paid += flt(payment.paid_amount, precision)
			elif payment.demand_subtype == "Principal":
				self.principal_amount_paid += flt(payment.paid_amount, precision)
			elif payment.demand_type == "Penalty":
				self.total_penalty_paid += flt(payment.paid_amount, precision)
			elif payment.demand_type == "Charges":
				self.total_charges_paid += flt(payment.paid_amount, precision)

		if flt(amount_paid, precision) > 0:
			if self.is_term_loan and not on_submit:
				if self.repayment_type == "Advance Payment":
					monthly_repayment_amount = frappe.db.get_value(
						"Loan Repayment Schedule",
						{"loan": self.against_loan, "status": "Active", "docstatus": 1},
						"monthly_repayment_amount",
					)

					if not (
						monthly_repayment_amount <= flt(amount_paid, precision) < (2 * monthly_repayment_amount)
					):
						frappe.throw(_("Amount for advance payment must be between one to two EMI amount"))

			pending_interest = flt(amounts.get("unaccrued_interest")) + flt(
				amounts.get("unbooked_interest")
			)

			if pending_interest > 0:
				if pending_interest > amount_paid:
					self.total_interest_paid += amount_paid
					self.unbooked_interest_paid += amount_paid
					amount_paid = 0
				else:
					self.total_interest_paid += pending_interest
					self.unbooked_interest_paid += pending_interest
					amount_paid -= pending_interest

			unbooked_penalty = flt(amounts.get("unbooked_penalty"))
			if unbooked_penalty > 0:
				if unbooked_penalty > amount_paid:
					self.total_penalty_paid += amount_paid
					self.unbooked_penalty_paid += amount_paid
					amount_paid = 0
				else:
					self.total_penalty_paid += unbooked_penalty
					self.unbooked_penalty_paid += unbooked_penalty
					amount_paid -= unbooked_penalty

			self.principal_amount_paid += flt(amount_paid, precision)
			self.total_interest_paid = flt(self.total_interest_paid, precision)
			self.principal_amount_paid = flt(self.principal_amount_paid, precision)

		if (
			self.auto_close_loan() or self.principal_amount_paid - self.pending_principal_amount > 0
		) and self.repayment_type not in ("Write Off Settlement", "Write Off Recovery"):
			self.excess_amount = self.principal_amount_paid - self.pending_principal_amount
			self.principal_amount_paid -= self.excess_amount

	def allocate_charges(self, amount_paid, demands):
		paid_charges = {}
		for charge in self.get("payable_charges"):
			paid_charges[charge.charge_code] = charge.amount

		for demand in demands:
			if paid_charges.get(demand.demand_subtype, 0) > 0:
				self.append(
					"repayment_details",
					{
						"loan_demand": demand.name,
						"paid_amount": paid_charges.get(demand.demand_subtype),
						"demand_type": "Charges",
						"demand_subtype": demand.demand_subtype,
						"sales_invoice": demand.sales_invoice,
					},
				)

				amount_paid -= paid_charges.get(demand.demand_subtype, 0)

		return amount_paid

	def apply_allocation_order(self, allocation_order, pending_amount, demands):
		"""Allocate amount based on allocation order"""
		allocation_order_doc = frappe.get_doc("Loan Demand Offset Order", allocation_order)
		for d in allocation_order_doc.get("components"):
			if d.demand_type == "EMI (Principal + Interest)" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "EMI", demands)
			if d.demand_type == "Principal" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Normal", demands)
				pending_amount = self.adjust_component(
					pending_amount, "EMI", demands, demand_subtype="Principal"
				)
				if self.repayment_type in (
					"Partial Settlement",
					"Full Settlement",
					"Write Off Recovery",
					"Write Off Settlement",
					"Principal Adjustment",
				):
					principal_amount_paid = sum(
						d.paid_amount for d in self.get("repayment_details") if d.demand_subtype == "Principal"
					)
					payable_principal_amount = self.pending_principal_amount - principal_amount_paid
					if flt(pending_amount) >= payable_principal_amount:
						self.principal_amount_paid += payable_principal_amount
						pending_amount -= payable_principal_amount
					else:
						self.principal_amount_paid += pending_amount
						pending_amount = 0

			if d.demand_type == "Interest" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Normal", demands)
				pending_amount = self.adjust_component(
					pending_amount, "EMI", demands, demand_subtype="Interest"
				)
			if d.demand_type == "Penalty" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Penalty", demands)
			if d.demand_type == "Charges" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Charges", demands)

		return pending_amount

	def adjust_component(self, amount_to_adjust, demand_type, demands, demand_subtype=None):
		for demand in demands:
			if demand.demand_type == demand_type:
				if not demand_subtype or demand.demand_subtype == demand_subtype:
					if amount_to_adjust >= demand.outstanding_amount:
						self.append(
							"repayment_details",
							{
								"loan_demand": demand.name,
								"paid_amount": demand.outstanding_amount,
								"demand_type": demand.demand_type,
								"demand_subtype": demand.demand_subtype,
								"sales_invoice": demand.sales_invoice,
							},
						)
						amount_to_adjust -= flt(demand.outstanding_amount)
					elif amount_to_adjust > 0:
						self.append(
							"repayment_details",
							{
								"loan_demand": demand.name,
								"paid_amount": amount_to_adjust,
								"demand_type": demand.demand_type,
								"demand_subtype": demand.demand_subtype,
								"sales_invoice": demand.sales_invoice,
							},
						)
						amount_to_adjust = 0

		return amount_to_adjust

	def make_gl_entries(self, cancel=0, adv_adj=0):
		if self.repayment_type == "Charges Waiver":
			return

		if cancel:
			make_reverse_gl_entries(voucher_type="Loan Repayment", voucher_no=self.name)
			return

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		gle_map = []

		payment_account = self.get_payment_account()

		account_details = frappe.db.get_value(
			"Loan Product",
			self.loan_product,
			[
				"interest_receivable_account",
				"penalty_receivable_account",
				"suspense_interest_income",
				"interest_income_account",
				"interest_waiver_account",
				"write_off_recovery_account",
				"customer_refund_account",
			],
			as_dict=1,
		)

		if flt(self.principal_amount_paid, precision) > 0:
			if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
				against_account = account_details.write_off_recovery_account
			else:
				against_account = self.loan_account

			self.add_gl_entry(payment_account, against_account, self.principal_amount_paid, gle_map)

		if flt(self.total_interest_paid, precision) > 0:
			if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
				against_account = account_details.write_off_recovery_account
			else:
				against_account = account_details.interest_receivable_account

			self.add_gl_entry(payment_account, against_account, self.total_interest_paid, gle_map)

		if flt(self.total_penalty_paid, precision) > 0:
			if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
				against_account = account_details.write_off_recovery_account
			else:
				against_account = account_details.penalty_receivable_account
			self.add_gl_entry(payment_account, against_account, self.total_penalty_paid, gle_map)

		if flt(self.excess_amount, precision):
			if self.auto_close_loan():
				against_account = account_details.interest_waiver_account
			else:
				against_account = account_details.customer_refund_account

			self.add_gl_entry(payment_account, against_account, self.excess_amount, gle_map)

		for repayment in self.get("repayment_details"):
			if repayment.demand_type == "Charges":
				against_account = frappe.db.get_value("Sales Invoice", repayment.sales_invoice, "debit_to")
				self.add_gl_entry(
					payment_account,
					against_account,
					repayment.paid_amount,
					gle_map,
					against_voucher_type="Sales Invoice",
					against_voucher=repayment.sales_invoice,
				)

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj)

	def add_gl_entry(
		self,
		account,
		against_account,
		amount,
		gl_entries,
		against_voucher_type=None,
		against_voucher=None,
	):
		remarks = self.get_remarks()

		payment_party_type = self.applicant_type
		payment_party = self.applicant

		if not (
			hasattr(self, "process_payroll_accounting_entry_based_on_employee")
			and self.process_payroll_accounting_entry_based_on_employee
		):
			payment_party_type = ""
			payment_party = ""

		gl_entries.append(
			self.get_gl_dict(
				{
					"account": account,
					"against": against_account,
					"debit": amount,
					"debit_in_account_currency": amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.against_loan,
					"remarks": _(remarks),
					"cost_center": self.cost_center,
					"posting_date": getdate(self.posting_date),
					"party_type": payment_party_type,
					"party": payment_party,
				}
			)
		)

		gl_entries.append(
			self.get_gl_dict(
				{
					"account": against_account,
					"party_type": self.applicant_type,
					"party": self.applicant,
					"against": account,
					"credit": amount,
					"credit_in_account_currency": amount,
					"against_voucher_type": against_voucher_type or "Loan",
					"against_voucher": against_voucher or self.against_loan,
					"remarks": _(remarks),
					"cost_center": self.cost_center,
					"posting_date": getdate(self.posting_date),
				}
			)
		)

	def get_payment_account(self):

		if self.repayment_type == "Charges Waiver":
			return

		payment_account_field_map = {
			"Interest Waiver": "interest_waiver_account",
			"Penalty Waiver": "penalty_waiver_account",
			"Principal Capitalization": "loan_account",
			"Loan Closure": "payment_account",
			"Principal Adjustment": "loan_account",
			"Interest Adjustment": "security_deposit_account",
			"Interest Carry Forward": "interest_income_account",
			"Security Deposit Adjustment": "security_deposit_account",
			"Subsidy Adjustments": "subsidy_adjustment_account",
		}

		if self.repayment_type in (
			"Normal Repayment",
			"Pre Payment",
			"Advance Payment",
			"Write Off Recovery",
			"Write Off Settlement",
			"Charge Payment",
			"Full Settlement",
			"Partial Settlement",
			"Principal Adjustment",
		):
			if hasattr(self, "repay_from_salary") and self.repay_from_salary:
				payment_account = self.payroll_payable_account
			else:
				payment_account = self.payment_account
		else:
			payment_account = frappe.db.get_value(
				"Loan Product", self.loan_product, payment_account_field_map.get(self.repayment_type)
			)

		return payment_account

	def get_charges_waiver_account(self, loan_product, charge):
		waiver_account = frappe.db.get_value(
			"Loan Charges", {"parent": loan_product, "charge_type": charge}, "waiver_account"
		)

		if not waiver_account:
			frappe.throw(
				_(
					"Waiver account not set for charge {0} in Loan Product {1}".format(
						frappe.bold(charge), frappe.bold(loan_product)
					)
				)
			)

		return waiver_account

	def get_remarks(self):
		if self.manual_remarks:
			remarks = self.manual_remarks
		elif self.shortfall_amount and self.amount_paid > self.shortfall_amount:
			remarks = "Shortfall repayment of {0}.<br>Repayment against loan {1}".format(
				self.shortfall_amount, self.against_loan
			)
		elif self.shortfall_amount:
			remarks = "Shortfall repayment of {0} against loan {1}".format(
				self.shortfall_amount, self.against_loan
			)
		else:
			remarks = "Repayment against loan " + self.against_loan

		if self.reference_number:
			remarks += " with reference no. {}".format(self.reference_number)

		return remarks


def create_repayment_entry(
	loan,
	applicant,
	company,
	posting_date,
	loan_product,
	payment_type,
	interest_payable,
	payable_principal_amount,
	amount_paid,
	penalty_amount=None,
	payroll_payable_account=None,
	process_payroll_accounting_entry_based_on_employee=0,
):

	lr = frappe.get_doc(
		{
			"doctype": "Loan Repayment",
			"against_loan": loan,
			"payment_type": payment_type,
			"company": company,
			"posting_date": posting_date,
			"applicant": applicant,
			"penalty_amount": penalty_amount,
			"interest_payable": interest_payable,
			"payable_principal_amount": payable_principal_amount,
			"amount_paid": amount_paid,
			"loan_product": loan_product,
			"payroll_payable_account": payroll_payable_account,
			"process_payroll_accounting_entry_based_on_employee": process_payroll_accounting_entry_based_on_employee,
		}
	).insert()

	return lr


def get_unpaid_demands(
	against_loan,
	posting_date=None,
	loan_product=None,
	demand_type=None,
	demand_subtype=None,
	limit=0,
	charges=None,
	loan_disbursement=None,
):
	if not posting_date:
		posting_date = getdate()

	precision = cint(frappe.db.get_default("currency_precision")) or 2

	loan_demand = frappe.qb.DocType("Loan Demand")
	query = get_demand_query()

	query = (
		query.where(
			(loan_demand.loan == against_loan)
			& (loan_demand.docstatus == 1)
			& (loan_demand.demand_date <= posting_date)
			& (Round(loan_demand.outstanding_amount, precision) > 0)
		)
		.orderby(loan_demand.demand_date)
		.orderby(loan_demand.disbursement_date)
		.orderby(loan_demand.repayment_schedule_detail)
		.orderby(loan_demand.demand_type)
		.orderby(loan_demand.creation)
	)

	if demand_subtype == "Charges":
		query = query.orderby(loan_demand.invoice_date)
	else:
		query = query.orderby(loan_demand.demand_subtype)

	if loan_product:
		query = query.where(loan_demand.loan_product == loan_product)

	if demand_type:
		query = query.where(loan_demand.demand_type == demand_type)

	if charges:
		query = query.where(loan_demand.demand_subtype.isin(charges))

	if demand_subtype:
		query = query.where(loan_demand.demand_subtype == demand_subtype)

	if limit:
		query = query.limit(limit)

	if loan_disbursement:
		query = query.where(loan_demand.loan_disbursement == loan_disbursement)

	loan_demands = query.run(as_dict=1)

	return loan_demands


def get_demand_query():
	loan_demand = frappe.qb.DocType("Loan Demand")
	return frappe.qb.from_(loan_demand).select(
		loan_demand.name,
		loan_demand.loan,
		loan_demand.demand_date,
		loan_demand.sales_invoice,
		loan_demand.loan_repayment_schedule,
		loan_demand.loan_disbursement,
		loan_demand.loan_product,
		loan_demand.company,
		loan_demand.loan_partner,
		(loan_demand.outstanding_amount).as_("outstanding_amount"),
		loan_demand.demand_subtype,
		loan_demand.demand_type,
	)


def get_pending_principal_amount(loan):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if loan.status in ("Disbursed", "Closed", "Active", "Written Off"):
		pending_principal_amount = flt(
			flt(loan.total_payment)
			+ flt(loan.debit_adjustment_amount)
			- flt(loan.credit_adjustment_amount)
			- flt(loan.total_principal_paid)
			- flt(loan.total_interest_payable)
			- flt(loan.refund_amount),
			precision,
		)
	else:
		pending_principal_amount = flt(
			flt(loan.disbursed_amount)
			+ flt(loan.debit_adjustment_amount)
			- flt(loan.credit_adjustment_amount)
			- flt(loan.total_principal_paid)
			- flt(loan.refund_amount),
			precision,
		)

	return pending_principal_amount


# This function returns the amounts that are payable at the time of loan repayment based on posting date
# So it pulls all the unpaid Loan Interest Accrual Entries and calculates the penalty if applicable


def get_demand_type(payment_type):
	demand_type = None
	demand_subtype = None

	if payment_type == "Interest Waiver":
		demand_type = "EMI"
		demand_subtype = "Interest"
	elif payment_type == "Penalty Waiver":
		demand_type = "Penalty"
		demand_subtype = "Penalty"
	elif payment_type in ("Charges Waiver", "Charge Payment"):
		demand_type = "Charges"

	return demand_type, demand_subtype


def get_amounts(
	amounts, against_loan, posting_date, with_loan_details=False, payment_type=None, charges=None
):
	demand_type, demand_subtype = get_demand_type(payment_type)

	against_loan_doc = frappe.get_cached_doc("Loan", against_loan)
	unpaid_demands = get_unpaid_demands(
		against_loan_doc.name,
		posting_date,
		demand_type=demand_type,
		demand_subtype=demand_subtype,
		charges=charges,
	)

	amounts = process_amount_for_loan(against_loan_doc, posting_date, unpaid_demands, amounts)

	if with_loan_details:
		return amounts, against_loan_doc.as_dict()
	else:
		return amounts


def process_amount_for_loan(loan, posting_date, demands, amounts):
	from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
		calculate_accrual_amount_for_loans,
		calculate_penal_interest_for_loans,
	)

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	total_pending_interest = 0
	charges = 0
	penalty_amount = 0
	payable_principal_amount = 0

	last_demand_date = get_last_demand_date(loan.name, posting_date)

	for demand in demands:
		if demand.demand_subtype == "Interest":
			total_pending_interest += demand.outstanding_amount
		elif demand.demand_subtype == "Principal":
			payable_principal_amount += demand.outstanding_amount
		elif demand.demand_subtype == "Penalty":
			penalty_amount += demand.outstanding_amount
		elif demand.demand_type == "Charges":
			charges += demand.outstanding_amount

	pending_principal_amount = get_pending_principal_amount(loan)

	unbooked_interest, accrued_interest = get_unbooked_interest(loan.name, posting_date)

	if getdate(posting_date) > getdate(last_demand_date):
		amounts["unaccrued_interest"] = calculate_accrual_amount_for_loans(
			loan, posting_date=posting_date, accrual_type="Regular", is_future_accrual=1
		)

		amounts["unbooked_penalty"] = calculate_penal_interest_for_loans(
			loan=loan, posting_date=posting_date, is_future_accrual=1
		)

	amounts["interest_accrued"] = accrued_interest
	amounts["total_charges_payable"] = charges
	amounts["pending_principal_amount"] = flt(pending_principal_amount, precision)
	amounts["payable_principal_amount"] = flt(payable_principal_amount, precision)
	amounts["interest_amount"] = flt(total_pending_interest, precision)
	amounts["penalty_amount"] = flt(penalty_amount, precision)
	amounts["payable_amount"] = flt(
		payable_principal_amount + total_pending_interest + penalty_amount + charges, precision
	)
	amounts["unbooked_interest"] = flt(unbooked_interest, precision)
	amounts["written_off_amount"] = flt(loan.written_off_amount, precision)
	amounts["unpaid_demands"] = demands
	amounts["due_date"] = last_demand_date
	amounts["excess_amount_paid"] = flt(loan.excess_amount_paid, precision)

	return amounts


@frappe.whitelist()
def get_bulk_due_details(loans, posting_date):
	loan_details = frappe.db.get_all(
		"Loan",
		fields=[
			"name",
			"company",
			"rate_of_interest",
			"is_term_loan",
			"written_off_amount",
			"status",
			"total_payment",
			"total_principal_paid",
			"total_interest_payable",
			"refund_amount",
			"debit_adjustment_amount",
			"credit_adjustment_amount",
			"disbursed_amount",
		],
		filters={"name": ("in", loans)},
	)

	loan_demands = get_all_demands(loans, posting_date)
	demand_map = {}
	for loan in loan_demands:
		demand_map.setdefault(loan.loan, [])
		demand_map[loan.loan].append(loan)

	due_details = []
	for loan in loan_details:
		amounts = init_amounts()
		demands = demand_map.get(loan.name, [])
		amounts = process_amount_for_loan(loan, posting_date, demands, amounts)
		amounts["loan"] = loan.name
		due_details.append(amounts)

	return due_details


def get_all_demands(loans, posting_date):
	loan_demand = frappe.qb.DocType("Loan Demand")

	query = get_demand_query()
	query = query.where(loan_demand.loan.isin(loans)).where(loan_demand.demand_date <= posting_date)

	return query.run(as_dict=1)


@frappe.whitelist()
def calculate_amounts(
	against_loan, posting_date, payment_type="", with_loan_details=False, charges=None
):
	amounts = init_amounts()

	if with_loan_details:
		amounts, loan_details = get_amounts(
			amounts,
			against_loan,
			posting_date,
			with_loan_details,
			payment_type=payment_type,
			charges=charges,
		)
	else:
		amounts = get_amounts(
			amounts, against_loan, posting_date, payment_type=payment_type, charges=charges
		)

	amounts["available_security_deposit"] = frappe.db.get_value(
		"Loan Security Deposit", {"loan": against_loan}, "sum(deposit_amount - allocated_amount)"
	)

	# update values for closure
	if payment_type in ("Loan Closure", "Full Settlement"):
		amounts["payable_principal_amount"] = amounts["pending_principal_amount"]
		amounts["interest_amount"] = (
			amounts["interest_amount"] + amounts["unbooked_interest"] + amounts["unaccrued_interest"]
		)
		amounts["payable_amount"] = (
			amounts["payable_principal_amount"] + amounts["interest_amount"] + amounts["penalty_amount"]
		)

	if with_loan_details:
		return {"amounts": amounts, "loan_details": loan_details}
	else:
		return amounts


def init_amounts():
	return {
		"penalty_amount": 0.0,
		"interest_amount": 0.0,
		"pending_principal_amount": 0.0,
		"payable_principal_amount": 0.0,
		"payable_amount": 0.0,
		"interest_accrued": 0.0,
		"unaccrued_interest": 0.0,
		"unbooked_interest": 0.0,
		"unbooked_penalty": 0.0,
		"due_date": "",
		"total_charges_payable": 0.0,
		"available_security_deposit": 0.0,
	}


def update_installment_counts(against_loan):
	loan_demand = frappe.qb.DocType("Loan Demand")
	loan_demands = (
		frappe.qb.from_(loan_demand)
		.select(
			loan_demand.loan_repayment_schedule,
			loan_demand.repayment_schedule_detail,
			Sum(loan_demand.outstanding_amount).as_("total_outstanding_amount"),
		)
		.where(
			(loan_demand.loan == against_loan)
			& (loan_demand.docstatus == 1)
			& (loan_demand.demand_type == "EMI")
		)
		.groupby(loan_demand.loan_repayment_schedule, loan_demand.repayment_schedule_detail)
		.run(as_dict=1)
	)

	count_details = {}
	for demand in loan_demands:
		count_details.setdefault(
			demand.loan_repayment_schedule,
			{"total_installments_raised": 0, "total_installments_paid": 0, "total_installments_overdue": 0},
		)

		count_details[demand.loan_repayment_schedule]["total_installments_raised"] += 1
		if demand.total_outstanding_amount <= 0:
			count_details[demand.loan_repayment_schedule]["total_installments_paid"] += 1
		else:
			count_details[demand.loan_repayment_schedule]["total_installments_overdue"] += 1

	for schedule, details in count_details.items():
		frappe.db.set_value(
			"Loan Repayment Schedule",
			schedule,
			{
				"total_installments_raised": details["total_installments_raised"],
				"total_installments_paid": details["total_installments_paid"],
				"total_installments_overdue": details["total_installments_overdue"],
			},
		)


def get_last_demand_date(loan, posting_date, demand_subtype="Interest"):
	from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
		get_last_disbursement_date,
	)

	last_demand_date = frappe.db.get_value(
		"Loan Demand",
		{
			"loan": loan,
			"docstatus": 1,
			"demand_subtype": demand_subtype,
			"demand_date": ("<=", posting_date),
		},
		"MAX(demand_date)",
	)

	if not last_demand_date:
		last_demand_date = get_last_disbursement_date(loan, posting_date)

	return last_demand_date


def get_unbooked_interest(loan, posting_date):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	accrued_interest = get_accrued_interest(loan, posting_date)
	total_demand_interest = get_demanded_interest(loan, posting_date)
	unbooked_interest = flt(accrued_interest, precision) - flt(total_demand_interest, precision)

	return unbooked_interest, accrued_interest


def get_accrued_interest(
	loan, posting_date, interest_type="Normal Interest", last_demand_date=None
):
	filters = {
		"loan": loan,
		"docstatus": 1,
		"posting_date": ("<=", posting_date),
		"interest_type": interest_type,
	}

	if last_demand_date:
		filters["posting_date"] = (">", last_demand_date)

	accrued_interest = frappe.db.get_value(
		"Loan Interest Accrual",
		filters,
		"SUM(interest_amount)",
	)

	return flt(accrued_interest)


def get_demanded_interest(loan, posting_date, demand_subtype="Interest"):
	demand_interest = frappe.db.get_value(
		"Loan Demand",
		{
			"loan": loan,
			"docstatus": 1,
			"demand_date": ("<=", posting_date),
			"demand_subtype": demand_subtype,
		},
		"SUM(demand_amount)",
	)

	return flt(demand_interest)


def get_net_paid_amount(loan):
	return frappe.db.get_value("Loan", {"name": loan}, "sum(total_amount_paid - refund_amount)")
