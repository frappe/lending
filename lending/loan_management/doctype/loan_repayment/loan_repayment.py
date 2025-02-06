# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.query_builder.functions import Round, Sum
from frappe.utils import add_days, cint, flt, get_datetime, getdate

import erpnext
from erpnext.accounts.general_ledger import (
	make_gl_entries,
	make_reverse_gl_entries,
	process_gl_map,
)
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
			self.against_loan,
			self.posting_date,
			payment_type=self.repayment_type,
			charges=charges,
			loan_disbursement=self.loan_disbursement,
			for_update=True,
		)
		self.set_missing_values(amounts)
		self.validate_repayment_type()
		self.validate_disbursement_link()
		if self.loan_disbursement:
			self.validate_open_disbursement()
		self.check_future_entries()
		self.validate_security_deposit_amount()
		self.validate_repayment_type()
		self.set_partner_payment_ratio()
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
					loan_disbursement=self.loan_disbursement,
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
		from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
			create_process_loan_classification,
		)
		from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
			process_daily_loan_demands,
		)
		from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
			process_loan_interest_accrual_for_loans,
		)

		reversed_accruals = []
		make_sales_invoice_for_charge(
			self.against_loan,
			"loan_repayment",
			self.name,
			self.posting_date,
			self.company,
			self.get("prepayment_charges"),
		)

		if self.repayment_type in ("Advance Payment", "Pre Payment"):
			reversed_accruals += self.reverse_future_accruals_and_demands()

		if not self.principal_amount_paid >= self.pending_principal_amount:
			if self.is_term_loan and self.repayment_type in ("Advance Payment", "Pre Payment"):
				amounts = calculate_amounts(
					self.against_loan,
					self.posting_date,
					payment_type=self.repayment_type,
					loan_disbursement=self.loan_disbursement,
					for_update=True,
				)
				self.allocate_amount_against_demands(amounts, on_submit=True)
				self.db_update_all()

				create_update_loan_reschedule(
					self.against_loan,
					self.posting_date,
					self.name,
					self.repayment_type,
					self.principal_amount_paid,
					loan_disbursement=self.loan_disbursement,
				)

				self.process_reschedule()

		if self.repayment_type not in ("Advance Payment", "Pre Payment") or (
			self.principal_amount_paid >= self.pending_principal_amount
		):
			self.book_interest_accrued_not_demanded()
			self.book_pending_principal()

		self.post_suspense_entries()

		self.update_paid_amounts()
		self.update_demands()
		self.update_security_deposit_amount()
		update_installment_counts(self.against_loan, loan_disbursement=self.loan_disbursement)

		if self.repayment_type == "Full Settlement":
			frappe.enqueue(self.post_write_off_settlements, enqueue_after_commit=True)

		update_loan_securities_values(self.against_loan, self.principal_amount_paid, self.doctype)
		self.create_loan_limit_change_log()
		self.make_gl_entries()

		if (
			self.is_term_loan
			and self.repayment_type
			not in (
				"Interest Waiver",
				"Penalty Waiver",
				"Charges Waiver",
				"Normal Repayment",
			)
			and not self.flags.from_repost
		):
			max_date = None
			reversed_accruals += reverse_loan_interest_accruals(
				self.against_loan,
				self.posting_date,
				interest_type="Penal Interest",
				is_npa=self.is_npa,
				on_payment_allocation=True,
			)

			if self.repayment_type in ("Full Settlement", "Write Off Settlement"):
				reversed_accruals += reverse_loan_interest_accruals(
					self.against_loan,
					self.posting_date,
					interest_type="Normal Interest",
					is_npa=self.is_npa,
					on_payment_allocation=True,
				)

			reverse_demands(self.against_loan, add_days(self.posting_date, 1), demand_type="Penalty")

			if reversed_accruals:
				create_process_loan_classification(
					posting_date=self.posting_date,
					loan_product=self.loan_product,
					loan=self.against_loan,
					payment_reference=self.name,
					is_backdated=1,
				)
			else:
				frappe.enqueue(
					create_process_loan_classification,
					posting_date=self.posting_date,
					loan_product=self.loan_product,
					loan=self.against_loan,
					is_backdated=0,
					enqueue_after_commit=True,
				)

			if reversed_accruals:
				dates = [getdate(d.get("posting_date")) for d in reversed_accruals]
				max_date = max(dates)
				if getdate(max_date) > getdate(self.posting_date):
					process_loan_interest_accrual_for_loans(
						posting_date=max_date, loan=self.against_loan, loan_product=self.loan_product
					)
					process_daily_loan_demands(posting_date=add_days(max_date, 1), loan=self.against_loan)

		if not self.is_term_loan:
			process_loan_interest_accrual_for_loans(
				posting_date=self.posting_date, loan=self.against_loan, loan_product=self.loan_product
			)

	def post_suspense_entries(self, cancel=0):
		from lending.loan_management.doctype.loan_write_off.loan_write_off import (
			write_off_suspense_entries,
		)

		base_amount_map = self.make_credit_note_for_charge_waivers(cancel=cancel)

		foreclosure_type = frappe.db.get_value(
			"Loan Adjustment", self.loan_adjustment, "foreclosure_type"
		)

		if self.is_npa and (
			self.repayment_type
			not in (
				"Interest Waiver",
				"Penalty Waiver",
				"Charges Waiver",
				"Principal Adjustment",
				"Write Off Recovery",
				"Write Off Settlement",
			)
			or foreclosure_type
		):
			additional_interest = sum(
				d.paid_amount for d in self.get("repayment_details") if d.demand_type == "Additional Interest"
			)
			total_penalty_paid = self.total_penalty_paid - additional_interest

			if foreclosure_type and self.repayment_type in (
				"Interest Waiver",
				"Penalty Waiver",
				"Charges Waiver",
			):
				is_write_off = 1
			else:
				is_write_off = 0

			if self.total_interest_paid > 0 or total_penalty_paid > 0:
				write_off_suspense_entries(
					self.against_loan,
					self.loan_product,
					self.posting_date,
					self.company,
					interest_amount=self.total_interest_paid,
					penalty_amount=total_penalty_paid,
					additional_interest_amount=additional_interest,
					on_payment_allocation=True,
					is_write_off=is_write_off,
					is_reverse=cancel,
				)

			if self.total_charges_paid > 0:
				self.write_off_charges(is_write_off, base_amount_map, is_reverse=cancel)

	def write_off_charges(self, is_write_off, base_amount_map, is_reverse=0):
		from lending.loan_management.doctype.loan_write_off.loan_write_off import write_off_charges

		charge_amount_map = {}
		charges = []

		for demand in self.get("repayment_details"):
			if demand.demand_type == "Charges":
				charge_amount_map[demand.demand_subtype] = demand.paid_amount
				charges.append(demand.demand_subtype)

		accounts = frappe._dict(
			frappe.db.get_all(
				"Loan Charges",
				{"parent": self.loan_product, "charge_type": ("in", charges)},
				[
					"charge_type",
					"suspense_account",
				],
				as_list=1,
			)
		)

		account_charge_map = {}
		for charge in charges:
			account_charge_map[accounts.get(charge)] = charge_amount_map.get(charge)

		write_off_charges(
			self.against_loan,
			self.posting_date,
			self.company,
			amount_details=account_charge_map,
			on_write_off=bool(is_write_off),
			base_amount_map=base_amount_map,
			is_reverse=is_reverse,
		)

	def book_pending_principal(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand

		overdue_principal_paid = 0
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		for d in self.get("repayment_details"):
			if d.demand_subtype == "Principal":
				overdue_principal_paid += d.paid_amount

		if self.principal_amount_paid - overdue_principal_paid > 0:
			amount = self.principal_amount_paid - overdue_principal_paid
			create_loan_demand(
				self.against_loan,
				self.posting_date,
				"EMI",
				"Principal",
				flt(amount, precision),
				paid_amount=flt(amount, precision),
				loan_disbursement=self.loan_disbursement,
			)

	def process_reschedule(self):
		loan_restructure = frappe.get_doc("Loan Restructure", {"loan_repayment": self.name})
		loan_restructure.flags.ignore_links = True
		loan_restructure.status = "Approved"
		loan_restructure.submit()

	def reverse_future_accruals_and_demands(self, on_settlement_or_closure=False):
		from lending.loan_management.doctype.loan_demand.loan_demand import reverse_demands
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)

		loan_repayment_schedule = ""
		if self.repayment_type in ("Pre Payment", "Advance Payment"):
			loan_restructure = frappe.db.get_value("Loan Restructure", {"loan_repayment": self.name})
			loan_repayment_schedule = frappe.db.get_value(
				"Loan Repayment Schedule", {"loan_restructure": loan_restructure}, "name"
			)

		accruals = reverse_loan_interest_accruals(
			self.against_loan,
			self.posting_date,
			interest_type="Normal Interest",
			is_npa=self.is_npa,
			on_payment_allocation=True,
			loan_disbursement=self.loan_disbursement,
			loan_repayment_schedule=loan_repayment_schedule,
		)

		reverse_demands(
			self.against_loan,
			self.posting_date,
			demand_type="EMI",
			loan_disbursement=self.loan_disbursement,
			on_settlement_or_closure=on_settlement_or_closure,
			loan_repayment_schedule=loan_repayment_schedule,
		)

		return accruals

	def set_repayment_account(self):
		if not self.payment_account and self.mode_of_payment:
			self.payment_account = frappe.db.get_value(
				"Mode of Payment Account",
				{"parent": self.mode_of_payment, "company": self.company},
				"default_account",
			)

		if not self.payment_account and self.bank_account:
			self.payment_account = frappe.db.get_value("Bank Account", self.bank_account, "account")

		repayment_account_map = {
			"Interest Waiver": "interest_waiver_account",
			"Penalty Waiver": "penalty_waiver_account",
			"Security Deposit Adjustment": "security_deposit_account",
		}

		if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
			write_off_recovery_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "write_off_recovery_account"
			)
			if not write_off_recovery_account:
				frappe.throw(
					_("Please set Write Off Recovery Account in Loan Product {0}").format(self.loan_product)
				)

			self.loan_account = write_off_recovery_account

		if not self.payment_account and repayment_account_map.get(self.repayment_type):
			self.payment_account = frappe.db.get_value(
				"Loan Product", self.loan_product, repayment_account_map.get(self.repayment_type)
			)

		if not self.payment_account:
			self.payment_account = frappe.db.get_value("Loan Product", self.loan_product, "payment_account")

	def make_credit_note_for_charge_waivers(self, cancel=0):
		base_amount_details = {}
		from lending.loan_management.doctype.loan_demand.loan_demand import make_credit_note

		if self.repayment_type == "Charges Waiver":
			if cancel:
				credit_notes = frappe.get_all(
					"Sales Invoice",
					{"loan_repayment": self.name, "docstatus": 1, "is_return": 1},
					pluck="name",
				)

				for credit_note in credit_notes:
					credit_note_doc = frappe.get_doc("Sales Invoice", credit_note)
					for item in credit_note_doc.get("items"):
						waiver_account = item.get("income_account")
						base_amount_details.setdefault(waiver_account, 0)
						base_amount_details[waiver_account] += abs(item.base_net_amount)

					credit_note_doc.flags.ignore_links = True
					credit_note_doc.cancel()

				return base_amount_details

			for demand in self.get("repayment_details"):
				demand_doc = frappe.get_doc("Loan Demand", demand.loan_demand)
				waiver_account = self.get_charges_waiver_account(self.loan_product, demand.demand_subtype)
				credit_note = make_credit_note(
					demand_doc.company,
					demand_doc.demand_subtype,
					demand_doc.applicant,
					demand_doc.loan,
					demand_doc.sales_invoice,
					self.posting_date,
					amount=demand.paid_amount,
					loan_repayment=self.name,
					waiver_account=waiver_account,
					posting_date=self.posting_date,
				)

				base_amount_details.setdefault(waiver_account, 0)
				base_amount_details[waiver_account] += abs(credit_note.base_net_total)

		return base_amount_details

	def create_loan_limit_change_log(self):
		create_loan_limit_change_log(
			loan=self.against_loan,
			event="Repayment",
			change_date=self.posting_date,
			value_type="Available Limit Amount",
			value_change=self.principal_amount_paid,
		)

	def on_cancel(self):
		from lending.loan_management.doctype.loan_npa_log.loan_npa_log import delink_npa_logs
		from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
			create_process_loan_classification,
		)
		from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
			process_daily_loan_demands,
		)
		from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
			process_loan_interest_accrual_for_loans,
		)

		self.flags.ignore_links = True
		self.check_future_accruals()
		self.mark_as_unpaid()
		self.update_demands(cancel=1)
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
			"Loan Repayment Repost",
			"Loan Adjustment",
		]
		self.make_gl_entries(cancel=1)
		self.post_suspense_entries(cancel=1)
		update_installment_counts(self.against_loan, loan_disbursement=self.loan_disbursement)

		max_demand_date = frappe.db.get_value(
			"Loan Interest Accrual", {"loan": self.against_loan}, "MAX(posting_date)"
		)
		if max_demand_date and getdate(max_demand_date) > getdate(self.posting_date):
			delink_npa_logs(self.against_loan, self.posting_date)
			process_loan_interest_accrual_for_loans(
				posting_date=max_demand_date, loan=self.against_loan, loan_product=self.loan_product
			)
			process_daily_loan_demands(posting_date=max_demand_date, loan=self.against_loan)
			create_process_loan_classification(
				posting_date=max_demand_date,
				loan_product=self.loan_product,
				loan=self.against_loan,
				is_backdated=1,
			)

	def cancel_charge_demands(self):
		sales_invoice = frappe.db.get_value("Sales Invoice", {"loan_repayment": self.name})
		if sales_invoice:
			loan_demands = frappe.db.get_all("Loan Demand", {"sales_invoice": sales_invoice}, pluck="name")
			for demand in loan_demands:
				charge_doc = frappe.get_doc("Loan Demand", demand)
				charge_doc.flags.ignore_links = True
				charge_doc.cancel()

	def cancel_loan_restructure(self):
		loan_restructure = frappe.db.get_value(
			"Loan Restructure", {"loan_repayment": self.name, "docstatus": 1}
		)
		if loan_restructure:
			restructure = frappe.get_doc("Loan Restructure", {"loan_repayment": self.name})
			restructure.flags.ignore_links = True
			restructure.cancel()

	def set_missing_values(self, amounts):
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		if not self.posting_date:
			self.posting_date = get_datetime()

		if not self.cost_center:
			self.cost_center = erpnext.get_default_cost_center(self.company)

		if not self.interest_payable or self.flags.from_repost:
			self.interest_payable = flt(amounts["interest_amount"], precision)

		if not self.penalty_amount or self.flags.from_repost:
			self.penalty_amount = flt(amounts["penalty_amount"], precision)

		self.pending_principal_amount = flt(amounts["pending_principal_amount"], precision)

		if not self.payable_principal_amount or self.flags.from_repost:
			self.payable_principal_amount = flt(amounts["payable_principal_amount"], precision)

		if not self.payable_amount or self.flags.from_repost:
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

		if self.repayment_type in ("Full Settlement", "Write Off Settlement"):
			self.total_charges_payable = amounts.get("total_charges_payable")

	def validate_disbursement_link(self):
		if self.repayment_schedule_type == "Line of Credit" and not self.loan_disbursement:
			frappe.throw(_("Please select Loan Disbursement for Line of Credit repayment"))

		if self.loan_disbursement:
			disbursements = frappe.get_all(
				"Loan Disbursement",
				{"against_loan": self.against_loan, "docstatus": 1},
				pluck="name",
			)
			if self.loan_disbursement not in disbursements:
				frappe.throw(_("Invalid Loan Disbursement linked for payment"))

	def check_future_entries(self):
		filters = {
			"posting_date": (">", self.posting_date),
			"docstatus": 1,
			"against_loan": self.against_loan,
		}

		if self.loan_disbursement and self.repayment_schedule_type == "Line of Credit":
			filters["loan_disbursement"] = self.loan_disbursement

		future_repayment_date = frappe.db.get_value(
			"Loan Repayment",
			filters,
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
				for_update=True,
			)

			if flt(self.amount_paid) > flt(available_deposit):
				frappe.throw(_("Amount paid cannot be greater than available security deposit"))
			if flt(self.amount_paid) > flt(self.payable_amount):
				frappe.throw(
					_(
						"The amount paid cannot be greater than the payable amount for Security Deposit Adjustment repayments."
					)
				)

	def validate_repayment_type(self):
		loan_status = frappe.db.get_value("Loan", self.against_loan, "status")

		if loan_status == "Closed":
			frappe.throw(_("Repayment cannot be made for closed loan"))

		if loan_status == "Written Off":
			if (
				self.repayment_type not in ("Write Off Recovery", "Write Off Settlement")
				and not self.is_write_off_waiver
			):
				frappe.throw(_("Repayment type can only be Write Off Recovery or Write Off Settlement"))
		elif self.repayment_type == "Normal Repayment":
			validate_repayment = frappe.get_cached_value(
				"Loan Product", self.loan_product, "validate_normal_repayment"
			)
			if validate_repayment and self.amount_paid > self.payable_amount:
				frappe.throw(_("Amount paid cannot be greater than payable amount"))
		elif loan_status != "Settled":
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

		if self.repayment_type in ("Interest Waiver", "Penalty Waiver", "Charges Waiver"):
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

	def validate_open_disbursement(self):
		loan_disbursement_status = frappe.get_value(
			"Loan Disbursement", self.loan_disbursement, "status"
		)
		if loan_disbursement_status == "Closed":
			frappe.throw(_(f"The Loan Disbursement {self.loan_disbursement} has been closed."))

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
				loan_disbursement=self.loan_disbursement,
			)

		if flt(self.unbooked_penalty_paid, precision) > 0:
			create_loan_demand(
				self.against_loan,
				self.posting_date,
				"Penalty",
				"Penalty",
				flt(self.unbooked_penalty_paid, precision),
				paid_amount=self.unbooked_penalty_paid,
				loan_disbursement=self.loan_disbursement,
			)

	def update_paid_amounts(self):
		loan = frappe.qb.DocType("Loan")

		if self.loan_disbursement:
			loan_disbursement = frappe.qb.DocType("Loan Disbursement")
			frappe.qb.update(loan_disbursement).set(
				loan_disbursement.principal_amount_paid,
				loan_disbursement.principal_amount_paid + self.principal_amount_paid,
			).where(loan_disbursement.name == self.loan_disbursement).run()

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
			if self.amount_paid >= self.payable_amount - auto_write_off_amount and self.auto_close_loan():
				if self.repayment_schedule_type != "Line of Credit":
					query = query.set(loan.status, "Closed")
					query = query.set(loan.closure_date, self.posting_date)
				self.update_repayment_schedule_status()
			else:
				if self.repayment_schedule_type != "Line of Credit":
					query = query.set(loan.status, "Active")
					query = query.set(loan.status, "Settled")
					query = query.set(loan.settlement_date, self.posting_date)
				self.update_repayment_schedule_status()

		elif self.auto_close_loan() and self.repayment_type in (
			"Normal Repayment",
			"Pre Payment",
			"Advance Payment",
			"Security Deposit Adjustment",
			"Loan Closure",
			"Principal Adjustment",
			"Penalty Waiver",
			"Interest Waiver",
			"Charges Waiver",
		):
			if self.repayment_schedule_type != "Line of Credit":
				query = query.set(loan.status, "Closed")
				query = query.set(loan.closure_date, self.posting_date)
			self.update_repayment_schedule_status()

			if not self.flags.from_repost:
				self.reverse_future_accruals_and_demands(on_settlement_or_closure=True)

		elif self.repayment_type == "Full Settlement":
			if self.repayment_schedule_type != "Line of Credit":
				query = query.set(loan.status, "Settled")
				query = query.set(loan.settlement_date, self.posting_date)
			self.update_repayment_schedule_status()

			if not self.flags.from_repost:
				self.reverse_future_accruals_and_demands(on_settlement_or_closure=True)

		query = self.update_limits(query, loan)
		query.run()

		update_shortfall_status(self.against_loan, self.principal_amount_paid)

	def post_write_off_settlements(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
		from lending.loan_management.doctype.loan_restructure.loan_restructure import (
			create_loan_repayment,
		)

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		last_demand_date = get_last_demand_date(
			self.against_loan, self.posting_date, loan_disbursement=self.loan_disbursement
		)

		unbooked_interest, accrued_interest = get_unbooked_interest(
			self.against_loan,
			self.posting_date,
			loan_disbursement=self.loan_disbursement,
			last_demand_date=last_demand_date,
		)

		unpaid_unbooked_interest = 0

		if flt(unbooked_interest - self.unbooked_interest_paid, precision) > 0:
			unpaid_unbooked_interest = unbooked_interest - self.unbooked_interest_paid
			create_loan_demand(
				self.against_loan,
				self.posting_date,
				"EMI",
				"Interest",
				flt(unpaid_unbooked_interest, precision),
			)

		if flt(self.interest_payable - self.total_interest_paid, precision) > 0:
			interest_amount = self.interest_payable - self.total_interest_paid
			create_loan_repayment(
				self.against_loan,
				self.posting_date,
				"Interest Waiver",
				interest_amount,
				is_write_off_waiver=1,
			)

		if flt(self.penalty_amount - self.total_penalty_paid, precision) > 0:
			penalty_amount = self.penalty_amount - self.total_penalty_paid
			create_loan_repayment(
				self.against_loan,
				self.posting_date,
				"Penalty Waiver",
				penalty_amount,
				is_write_off_waiver=1,
			)

		if flt(self.total_charges_payable - self.total_charges_paid, precision) > 0:
			charges_amount = self.total_charges_payable - self.total_charges_paid
			create_loan_repayment(
				self.against_loan,
				self.posting_date,
				"Charges Waiver",
				charges_amount,
				is_write_off_waiver=1,
			)

		if (
			flt(self.payable_principal_amount - self.principal_amount_paid, 2) > 0
			and self.repayment_type == "Full Settlement"
		):
			principal_amount = self.payable_principal_amount - self.principal_amount_paid
			loan_write_off = frappe.new_doc("Loan Write Off")
			loan_write_off.loan = self.against_loan
			loan_write_off.posting_date = self.posting_date
			loan_write_off.write_off_amount = principal_amount
			loan_write_off.is_settlement_write_off = 1
			loan_write_off.save()
			loan_write_off.submit()

	def update_repayment_schedule_status(self, cancel=0):
		if cancel:
			status = "Active"
			current_status = "Closed"
		else:
			status = "Closed"
			current_status = "Active"

		filters = {"loan": self.against_loan, "docstatus": 1, "status": current_status}

		if self.loan_disbursement:
			filters["loan_disbursement"] = self.loan_disbursement
			if cancel:
				frappe.db.set_value("Loan Disbursement", self.loan_disbursement, "status", "Submitted")
			if status == "Closed":
				frappe.db.set_value("Loan Disbursement", self.loan_disbursement, "status", status)

		repayment_schedule = frappe.get_value("Loan Repayment Schedule", filters, "name")
		if repayment_schedule:
			frappe.db.set_value("Loan Repayment Schedule", repayment_schedule, "status", status)

	def auto_close_loan(self):
		auto_close = False

		auto_write_off_amount, excess_amount_limit = frappe.db.get_value(
			"Loan Product", self.loan_product, ["write_off_amount", "excess_amount_acceptance_limit"]
		)

		shortfall_amount = self.pending_principal_amount - self.principal_amount_paid

		if self.repayment_type in ("Interest Waiver", "Penalty Waiver", "Charges Waiver"):
			total_payable = (
				frappe.db.get_value(
					"Loan Demand",
					{
						"loan": self.against_loan,
						"docstatus": 1,
						"outstanding_amount": (">", 0),
						"demand_date": ("<=", self.posting_date),
					},
					"sum(outstanding_amount)",
				)
				or 0
			)
		else:
			total_payable = self.payable_amount

		if (
			auto_write_off_amount
			and shortfall_amount > 0
			and shortfall_amount <= auto_write_off_amount
			and flt(total_payable - self.amount_paid) <= flt(shortfall_amount)
		):
			auto_close = True

		excess_amount = self.principal_amount_paid - self.pending_principal_amount
		if excess_amount > 0 and excess_amount <= excess_amount_limit:
			auto_close = True

		if (
			self.principal_amount_paid >= self.pending_principal_amount
			and not flt(shortfall_amount)
			and flt(self.excess_amount) <= flt(excess_amount_limit)
			and flt(total_payable - self.amount_paid) <= flt(auto_write_off_amount)
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
			"Security Deposit Adjustment",
		):
			loan = frappe.qb.DocType("Loan")

			loan_status, repayment_schedule_type = frappe.db.get_value(
				"Loan", self.against_loan, ["status", "repayment_schedule_type"]
			)

			if self.loan_disbursement:
				loan_disbursement = frappe.qb.DocType("Loan Disbursement")
				frappe.qb.update(loan_disbursement).set(
					loan_disbursement.principal_amount_paid,
					loan_disbursement.principal_amount_paid - self.principal_amount_paid,
				).where(loan_disbursement.name == self.loan_disbursement).run()

			query = (
				frappe.qb.update(loan)
				.set(loan.total_amount_paid, loan.total_amount_paid - self.amount_paid)
				.set(loan.total_principal_paid, loan.total_principal_paid - self.principal_amount_paid)
				.where(loan.name == self.against_loan)
			)

			if self.repayment_type == "Write Off Settlement":
				query = query.set(loan.status, "Written Off")
				self.update_repayment_schedule_status(cancel=1)
			elif self.repayment_type == "Full Settlement":
				query = query.set(loan.status, "Disbursed")
				self.update_repayment_schedule_status(cancel=1)
			elif loan_status == "Closed":
				if repayment_schedule_type == "Line of Credit":
					query = query.set(loan.status, "Active")
				else:
					query = query.set(loan.status, "Disbursed")
					self.update_repayment_schedule_status(cancel=1)

			if self.repayment_schedule_type == "Line of Credit" and self.loan_disbursement:
				self.update_repayment_schedule_status(cancel=1)

			if flt(self.excess_amount) > 0:
				query = query.set(loan.excess_amount_paid, loan.excess_amount_paid - self.excess_amount)

			query = self.update_limits(query, loan, cancel=1)
			query.run()

	def update_demands(self, cancel=0):
		loan_demand = frappe.qb.DocType("Loan Demand")
		for payment in self.repayment_details:
			paid_amount = payment.paid_amount
			partner_share = flt(payment.partner_share)

			if cancel:
				paid_amount = -1 * flt(payment.paid_amount)
				partner_share = -1 * flt(payment.partner_share)

			if self.repayment_type in ("Interest Waiver", "Penalty Waiver", "Charges Waiver"):
				paid_amount_field = "waived_amount"
			else:
				paid_amount_field = "paid_amount"

			frappe.qb.update(loan_demand).set(
				loan_demand[paid_amount_field], loan_demand[paid_amount_field] + paid_amount
			).set(
				loan_demand.outstanding_amount, loan_demand.outstanding_amount - paid_amount
			).set(
				loan_demand.partner_share_allocated, loan_demand.partner_share_allocated + partner_share
			).where(
				loan_demand.name == payment.loan_demand
			).run()

	def update_limits(self, query, loan, cancel=0):
		principal_amount_paid = self.principal_amount_paid
		if cancel:
			principal_amount_paid = -1 * flt(self.principal_amount_paid)

		if self.repayment_schedule_type == "Line of Credit":
			query = (
				query.set(loan.available_limit_amount, loan.available_limit_amount + principal_amount_paid)
				.set(loan.utilized_limit_amount, loan.utilized_limit_amount - principal_amount_paid)
				.where(loan.name == self.against_loan)
			)

		return query

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
		if self.flags.from_repost:
			return

		filters = {
			"posting_date": (">", self.posting_date),
			"docstatus": 1,
			"against_loan": self.against_loan,
		}

		if self.loan_disbursement:
			filters["loan_disbursement"] = self.loan_disbursement

		future_repayment = frappe.db.get_value(
			"Loan Repayment",
			filters,
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

		total_demanded_principal = 0
		self.principal_amount_paid = 0
		self.total_penalty_paid = 0
		self.total_interest_paid = 0
		self.total_charges_paid = 0
		self.unbooked_interest_paid = 0
		self.unbooked_penalty_paid = 0
		self.total_partner_principal_share = 0
		self.total_partner_interest_share = 0
		self.excess_amount = 0
		settlement_date = None

		for demand in amounts.get("unpaid_demands"):
			if demand.get("demand_subtype") == "Principal":
				total_demanded_principal += demand.get("outstanding_amount")

		if (
			self.repayment_type in ("Write Off Recovery", "Write Off Settlement")
			or loan_status == "Settled"
		):
			if not self.total_charges_payable:
				self.total_charges_payable = 0

			if loan_status == "Settled":
				settlement_date = frappe.db.get_value("Loan", self.against_loan, "settlement_date")

			waiver_details = get_write_off_waivers(self.against_loan, self.posting_date)
			recovery_details = get_write_off_recovery_details(
				self.against_loan, self.posting_date, settlement_date=settlement_date
			)
			pending_interest = flt(waiver_details.get("Interest Waiver")) - flt(
				recovery_details.get("total_interest")
			)
			pending_penalty = flt(waiver_details.get("Penalty Waiver")) - flt(
				recovery_details.get("total_penalty")
			)

			pending_charges = flt(waiver_details.get("Charges Waiver")) - flt(
				recovery_details.get("total_charges")
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

			self.total_charges_payable += pending_charges

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
			elif (
				self.repayment_type in ("Partial Settlement", "Full Settlement", "Principal Adjustment")
				or loan_status == "Settled"
			):
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
				allocation_order, amount_paid, amounts.get("unpaid_demands"), status=loan_status
			)

		for payment in self.repayment_details:
			if payment.demand_subtype == "Interest":
				self.total_interest_paid += flt(payment.paid_amount, precision)
				self.total_partner_interest_share += flt(payment.partner_share, precision)
			elif payment.demand_subtype == "Principal":
				self.principal_amount_paid += flt(payment.paid_amount, precision)
				self.total_partner_principal_share += flt(payment.partner_share, precision)
			elif payment.demand_type in ("Penalty", "Additional Interest"):
				self.total_penalty_paid += flt(payment.paid_amount, precision)
			elif payment.demand_type == "Charges":
				self.total_charges_paid += flt(payment.paid_amount, precision)

		if flt(amount_paid, precision) > 0:
			if self.is_term_loan and not on_submit:
				if self.repayment_type == "Advance Payment":
					filters = {"loan": self.against_loan, "status": "Active", "docstatus": 1}

					if self.loan_disbursement:
						filters["loan_disbursement"] = self.loan_disbursement

					monthly_repayment_amount = frappe.db.get_value(
						"Loan Repayment Schedule",
						filters,
						"monthly_repayment_amount",
					)

					if (flt(amount_paid, precision) < monthly_repayment_amount) or (
						flt(amount_paid, precision) > (2 * monthly_repayment_amount)
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
			if unbooked_penalty > 0 and self.repayment_type != "Interest Waiver":
				if unbooked_penalty > amount_paid:
					self.total_penalty_paid += amount_paid
					self.unbooked_penalty_paid += amount_paid
					amount_paid = 0
				else:
					self.total_penalty_paid += unbooked_penalty
					self.unbooked_penalty_paid += unbooked_penalty
					amount_paid -= unbooked_penalty

			if (
				flt(self.total_charges_payable) > 0
				and amount_paid > 0
				and self.repayment_type in ("Write Off Recovery", "Write Off Settlement")
			):
				if flt(self.total_charges_payable) > amount_paid:
					self.total_charges_paid += amount_paid
					amount_paid = 0
				else:
					self.total_charges_paid += self.total_charges_payable
					amount_paid -= self.total_charges_payable

			if self.repayment_type not in ("Interest Waiver", "Penalty Waiver", "Charges Waiver"):
				self.principal_amount_paid += flt(amount_paid, precision)
			elif self.repayment_type == "Penalty Waiver":
				self.total_penalty_paid += amount_paid
				amount_paid = 0
			elif self.repayment_type == "Interest Waiver":
				self.total_interest_paid += amount_paid
				amount_paid = 0

			self.total_interest_paid = flt(self.total_interest_paid, precision)
			self.principal_amount_paid = flt(self.principal_amount_paid, precision)

		if (
			self.auto_close_loan() or self.principal_amount_paid - self.pending_principal_amount > 0
		) and self.repayment_type not in ("Write Off Settlement", "Write Off Recovery"):
			self.excess_amount = self.principal_amount_paid - self.pending_principal_amount
			self.principal_amount_paid -= self.excess_amount
		elif self.repayment_type == "Write Off Settlement" and (
			self.auto_close_loan() or (self.principal_amount_paid - self.payable_principal_amount > 0)
		):
			self.excess_amount = self.principal_amount_paid - self.payable_principal_amount
			self.principal_amount_paid -= self.excess_amount

		total_paid_principal_demand = sum(
			d.paid_amount for d in self.get("repayment_details") if d.demand_subtype == "Principal"
		)
		if flt(self.excess_amount, precision) < 0 and (
			flt(total_demanded_principal, precision) - flt(total_paid_principal_demand, precision)
			== abs(flt(self.excess_amount, precision))
		):
			last_principal_demand = self.get("repayment_details")[-1]
			last_principal_demand.paid_amount += abs(self.excess_amount)

	def set_partner_payment_ratio(self):
		if self.get("loan_partner"):
			precision = cint(frappe.db.get_default("currency_precision")) or 2

			schedule_details = frappe.db.get_value(
				"Loan Repayment Schedule",
				{"loan": self.against_loan, "docstatus": 1, "status": "Active"},
				[
					"monthly_repayment_amount",
					"partner_monthly_repayment_amount",
					"partner_repayment_schedule_type",
					"partner_loan_share_percentage",
					"partner_base_interest_rate",
				],
				as_dict=1,
			)

			partner_details = frappe.db.get_value(
				"Loan Partner",
				self.loan_partner,
				[
					"repayment_schedule_type",
					"partner_loan_share_percentage",
					"partner_base_interest_rate",
				],
				as_dict=1,
			)

			self.loan_partner_share_percentage = schedule_details.partner_loan_share_percentage
			self.loan_partner_repayment_schedule_type = schedule_details.partner_repayment_schedule_type
			self.partner_base_interest_rate = partner_details.partner_base_interest_rate

			if partner_details.repayment_schedule_type == "Collection at partner's percentage":
				self.loan_partner_payment_ratio = partner_details.partner_loan_share_percentage / 100
			elif partner_details.repayment_schedule_type == "EMI (PMT) based":
				self.loan_partner_payment_ratio = (
					flt(
						(
							(
								schedule_details.partner_monthly_repayment_amount
								/ schedule_details.monthly_repayment_amount
							)
							* 100
						),
						precision,
					)
					/ 100
				)

			elif partner_details.repayment_schedule_type == "POS reduction plus interest at partner ROI":
				loan_repayment_schedule = frappe.db.get_value(
					"Loan Repayment Schedule", {"docstatus": 1, "status": "Active", "loan": self.against_loan}
				)

				borrower_interest, payment_date = frappe.db.get_value(
					"Repayment Schedule", {"parent": loan_repayment_schedule}, ["interest_amount", "payment_date"]
				)

				colender_interest = frappe.db.get_value(
					"Co-Lender Schedule",
					{"parent": loan_repayment_schedule, "payment_date": payment_date},
					"interest_amount",
				)

				self.loan_partner_payment_ratio = flt(colender_interest / borrower_interest)

	def allocate_charges(self, amount_paid, demands):
		paid_charges = {}
		for charge in self.get("payable_charges"):
			paid_charges[charge.charge_code] = charge.amount

		for demand in demands:
			if amount_paid > 0 and paid_charges.get(demand.demand_subtype, 0) > 0:
				if amount_paid > paid_charges.get(demand.demand_subtype, 0):
					paid_amount = paid_charges.get(demand.demand_subtype, 0)
				else:
					paid_amount = amount_paid

				self.append(
					"repayment_details",
					{
						"loan_demand": demand.name,
						"paid_amount": paid_amount,
						"demand_type": "Charges",
						"demand_subtype": demand.demand_subtype,
						"sales_invoice": demand.sales_invoice,
					},
				)

				amount_paid -= paid_amount

		return amount_paid

	def apply_allocation_order(self, allocation_order, pending_amount, demands, status=None):
		"""Allocate amount based on allocation order"""
		allocation_order_doc = frappe.get_doc("Loan Demand Offset Order", allocation_order)
		for d in allocation_order_doc.get("components"):
			if d.demand_type == "EMI (Principal + Interest)" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "BPI", demands)
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
				) or (
					status == "Settled"
					and self.repayment_type not in ("Interest Waiver", "Penalty Waiver", "Charges Waiver")
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
			if d.demand_type == "Additional Interest" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Additional Interest", demands)
			if d.demand_type == "Charges" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Charges", demands)

		return pending_amount

	def adjust_component(self, amount_to_adjust, demand_type, demands, demand_subtype=None):
		partner_share = 0
		if self.get("loan_partner"):
			partner_share = self.get_overall_partner_share(amount_to_adjust) or 0

		for demand in demands:
			paid_amount = 0
			partner_share_paid = 0

			if demand.demand_type == demand_type:
				if not demand_subtype or demand.demand_subtype == demand_subtype:
					if amount_to_adjust >= demand.outstanding_amount:
						paid_amount = flt(demand.outstanding_amount)
						amount_to_adjust -= flt(demand.outstanding_amount)

						if demand_type == "EMI" and self.get("loan_partner"):
							partner_share_paid = self.get_loan_partner_share_paid(0, paid_amount, demand) or 0
							partner_share -= partner_share_paid
					elif amount_to_adjust > 0:
						paid_amount = amount_to_adjust
						amount_to_adjust = 0

						if demand_type == "EMI" and self.get("loan_partner"):
							partner_share_paid = (
								self.get_loan_partner_share_paid(partner_share, paid_amount, demand) or 0
							)
							partner_share -= partner_share_paid

					if paid_amount > 0:
						self.append(
							"repayment_details",
							{
								"loan_demand": demand.name,
								"paid_amount": paid_amount,
								"demand_type": demand.demand_type,
								"demand_subtype": demand.demand_subtype,
								"sales_invoice": demand.sales_invoice,
								"partner_share": partner_share_paid,
							},
						)

		return amount_to_adjust

	def get_loan_partner_share_paid(self, amount_to_adjust, paid_amount, demand):
		if self.loan_partner_repayment_schedule_type == "EMI (PMT) based":
			return flt(amount_to_adjust) or flt(demand.partner_outstanding)
		elif self.loan_partner_repayment_schedule_type == "Collection at partner's percentage":
			return flt(self.loan_partner_payment_ratio * paid_amount)
		elif self.loan_partner_repayment_schedule_type == "POS reduction plus interest at partner ROI":
			if demand.demand_subtype == "Interest":
				return flt(self.loan_partner_payment_ratio * paid_amount)
			elif demand.demand_subtype == "Principal":
				return flt(self.loan_partner_share_percentage * paid_amount) / 100

	def get_overall_partner_share(self, paid_amount):
		if self.loan_partner_repayment_schedule_type == "EMI (PMT) based":
			return flt(self.loan_partner_payment_ratio * paid_amount)
		elif self.loan_partner_repayment_schedule_type == "Collection at partner's percentage":
			return flt(self.loan_partner_payment_ratio * paid_amount)
		elif self.loan_partner_repayment_schedule_type == "POS reduction plus interest at partner ROI":
			return flt(self.loan_partner_share_percentage * paid_amount)

	def make_gl_entries(self, cancel=0, adv_adj=0):
		if self.repayment_type == "Charges Waiver":
			return

		if cancel:
			make_reverse_gl_entries(voucher_type="Loan Repayment", voucher_no=self.name)
			return

		gle_map = self.get_gl_map()

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj)

	def get_gl_map(self):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		gle_map = []
		payment_account = self.get_payment_account()

		account_details = frappe.db.get_value(
			"Loan Product",
			self.loan_product,
			[
				"interest_receivable_account",
				"penalty_receivable_account",
				"additional_interest_receivable",
				"suspense_interest_income",
				"interest_income_account",
				"penalty_income_account",
				"additional_interest_income",
				"interest_waiver_account",
				"penalty_waiver_account",
				"additional_interest_waiver",
				"write_off_recovery_account",
				"customer_refund_account",
			],
			as_dict=1,
		)

		if flt(self.principal_amount_paid, precision) > 0:
			self.add_gl_entry(payment_account, self.loan_account, self.principal_amount_paid, gle_map)

		if flt(self.total_interest_paid, precision) > 0:
			if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
				against_account = self.loan_account
			else:
				against_account = account_details.interest_receivable_account

			self.add_gl_entry(payment_account, against_account, self.total_interest_paid, gle_map)

			if self.repayment_type == "Interest Waiver" and not self.is_npa:
				self.add_gl_entry(
					account_details.interest_income_account,
					self.payment_account,
					self.total_interest_paid,
					gle_map,
					is_waiver_entry=True,
				)

		additional_interest = sum(
			d.paid_amount for d in self.get("repayment_details") if d.demand_type == "Additional Interest"
		)
		total_penalty_paid = self.total_penalty_paid - additional_interest

		if flt(total_penalty_paid, precision) > 0:
			if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
				against_account = self.loan_account
			else:
				against_account = account_details.penalty_receivable_account

			self.add_gl_entry(payment_account, against_account, total_penalty_paid, gle_map)

			if self.repayment_type == "Penalty Waiver" and not self.is_npa:
				self.add_gl_entry(
					account_details.penalty_income_account,
					self.payment_account,
					total_penalty_paid,
					gle_map,
					is_waiver_entry=True,
				)

		if flt(additional_interest, precision) > 0:
			if self.repayment_type == "Penalty Waiver":
				payment_account = account_details.additional_interest_waiver

			if self.repayment_type in ("Write Off Recovery", "Write Off Settlement"):
				against_account = self.loan_account
			else:
				against_account = account_details.additional_interest_receivable

			self.add_gl_entry(payment_account, against_account, additional_interest, gle_map)

			if self.repayment_type == "Penalty Waiver" and not self.is_npa:
				self.add_gl_entry(
					account_details.additional_interest_income,
					account_details.additional_interest_waiver,
					additional_interest,
					gle_map,
					is_waiver_entry=True,
				)

		if flt(self.excess_amount, precision):
			if self.auto_close_loan():
				against_account = account_details.interest_waiver_account
			else:
				against_account = account_details.customer_refund_account
				if not against_account:
					frappe.throw(
						_("Please set Customer Refund Account in Loan Product {0}").format(self.loan_product)
					)

			self.add_gl_entry(payment_account, against_account, self.excess_amount, gle_map)

		if flt(self.total_charges_paid, precision) > 0 and self.repayment_type in (
			"Write Off Recovery",
			"Write Off Settlement",
		):
			against_account = self.payment_account
			self.add_gl_entry(self.payment_account, against_account, self.total_charges_paid, gle_map)

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

		self.add_loan_partner_gl_entries(gle_map)
		self.add_round_off_gl_entry(gle_map)

		gle_map = process_gl_map(gle_map)

		return gle_map

	def add_round_off_gl_entry(self, gle_map):

		if self.repayment_type == "Penalty Waiver":
			return

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		payment_account = self.get_payment_account()
		total_payment_amount = sum(d.debit for d in gle_map if d.account == payment_account)

		diff = flt(total_payment_amount - self.amount_paid, precision)

		if 0 < abs(diff) < 1:
			round_off_account = frappe.db.get_value("Company", self.company, "round_off_account")
			self.add_gl_entry(payment_account, round_off_account, -1 * diff, gle_map, is_waiver_entry=True)

	def add_loan_partner_gl_entries(self, gle_map):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		partner_details = frappe.db.get_value(
			"Loan Partner",
			self.loan_partner,
			["credit_account", "payable_account", "partner_interest_share", "enable_partner_accounting"],
			as_dict=1,
		)
		if self.get("loan_partner") and partner_details.enable_partner_accounting:
			if flt(self.total_partner_principal_share, precision) > 0:
				self.add_gl_entry(
					partner_details.credit_account,
					partner_details.payable_account,
					self.total_partner_principal_share,
					gle_map,
				)

			if flt(self.total_partner_interest_share, precision) > 0:
				self.add_gl_entry(
					partner_details.partner_interest_share,
					partner_details.payable_account,
					self.total_partner_interest_share,
					gle_map,
				)

	def add_gl_entry(
		self,
		account,
		against_account,
		amount,
		gl_entries,
		against_voucher_type=None,
		against_voucher=None,
		is_waiver_entry=False,
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
					"party_type": self.applicant_type if not is_waiver_entry else "",
					"party": self.applicant if not is_waiver_entry else "",
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
			"Additional Interest Waiver": "additional_interest_waiver",
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
			"Loan Closure",
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
	emi_wise=False,
	sales_invoice=None,
	for_update=False,
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

	if demand_type and demand_type != "Penalty":
		query = query.where(loan_demand.demand_type == demand_type)

	if charges:
		query = query.where(loan_demand.demand_subtype.isin(charges))

	if sales_invoice:
		query = query.where(loan_demand.sales_invoice == sales_invoice)

	if demand_subtype:
		if demand_subtype != "Penalty":
			query = query.where(loan_demand.demand_subtype == demand_subtype)
		else:
			query = query.where(loan_demand.demand_type.isin(["Penalty", "Additional Interest"]))
			query = query.where(loan_demand.demand_subtype.isin(["Penalty", "Additional Interest"]))

	if limit:
		query = query.limit(limit)

	if loan_disbursement:
		query = query.where(loan_demand.loan_disbursement == loan_disbursement)

	if emi_wise:
		query = query.where(loan_demand.demand_type == "EMI")
		query = query.where(loan_demand.repayment_schedule_detail.isnotnull())
		query = query.select(Sum(loan_demand.outstanding_amount).as_("pending_amount"))
		query = query.select(loan_demand.repayment_schedule_detail)
		query = query.groupby(loan_demand.repayment_schedule_detail)

	if for_update:
		query = query.for_update()

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
		(loan_demand.partner_share - loan_demand.partner_share_allocated).as_("partner_outstanding"),
		loan_demand.demand_subtype,
		loan_demand.demand_type,
	)


def get_pending_principal_amount(loan, loan_disbursement=None):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if loan_disbursement and loan.repayment_schedule_type == "Line of Credit":
		pending_principal_amount = frappe.db.get_value(
			"Loan Disbursement", loan_disbursement, "sum(disbursed_amount - principal_amount_paid)"
		)
	elif loan.status == "Cancelled":
		pending_principal_amount = 0
	elif (
		loan.status in ("Disbursed", "Closed", "Active", "Written Off")
		and loan.repayment_schedule_type != "Line of Credit"
	):
		pending_principal_amount = flt(
			flt(loan.total_payment)
			+ flt(loan.debit_adjustment_amount)
			- flt(loan.credit_adjustment_amount)
			- flt(loan.total_principal_paid)
			- flt(loan.total_interest_payable),
			precision,
		)
	else:
		pending_principal_amount = flt(
			flt(loan.disbursed_amount)
			+ flt(loan.debit_adjustment_amount)
			- flt(loan.credit_adjustment_amount)
			- flt(loan.total_principal_paid),
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
	elif payment_type == "Advance Payment":
		demand_type = "EMI"

	return demand_type, demand_subtype


def get_amounts(
	amounts,
	against_loan,
	posting_date,
	with_loan_details=False,
	payment_type=None,
	charges=None,
	loan_disbursement=None,
	for_update=False,
):
	demand_type, demand_subtype = get_demand_type(payment_type)

	against_loan_doc = frappe.get_doc("Loan", against_loan, for_update=for_update)
	unpaid_demands = get_unpaid_demands(
		against_loan_doc.name,
		posting_date,
		demand_type=demand_type,
		demand_subtype=demand_subtype,
		charges=charges,
		loan_disbursement=loan_disbursement,
		for_update=for_update,
	)

	amounts = process_amount_for_loan(
		against_loan_doc,
		posting_date,
		unpaid_demands,
		amounts,
		loan_disbursement=loan_disbursement,
		status=against_loan_doc.status,
		payment_type=payment_type,
	)

	if with_loan_details:
		return amounts, against_loan_doc.as_dict()
	else:
		return amounts


def process_amount_for_loan(
	loan, posting_date, demands, amounts, loan_disbursement=None, status=None, payment_type=None
):
	from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
		calculate_accrual_amount_for_loans,
		calculate_penal_interest_for_loans,
	)

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	total_pending_interest = 0
	charges = 0
	penalty_amount = 0
	payable_principal_amount = 0
	is_backdated = 0

	last_demand_date = get_last_demand_date(
		loan.name, posting_date, loan_disbursement=loan_disbursement, status=status
	)
	latest_accrual_date = get_latest_accrual_date(
		loan.name, posting_date, loan_disbursement=loan_disbursement
	)

	if latest_accrual_date and getdate(latest_accrual_date) > getdate(posting_date):
		is_backdated = 1

	for demand in demands:
		if demand.demand_subtype == "Interest":
			total_pending_interest += demand.outstanding_amount
		elif demand.demand_subtype == "Principal":
			payable_principal_amount += demand.outstanding_amount
		elif demand.demand_subtype in ("Penalty", "Additional Interest"):
			penalty_amount += demand.outstanding_amount
		elif demand.demand_type == "Charges":
			charges += demand.outstanding_amount

	pending_principal_amount = get_pending_principal_amount(loan, loan_disbursement=loan_disbursement)

	unbooked_interest, accrued_interest = get_unbooked_interest(
		loan.name, posting_date, loan_disbursement=loan_disbursement, last_demand_date=last_demand_date
	)

	if getdate(posting_date) > getdate(latest_accrual_date) or is_backdated:
		amounts["unaccrued_interest"] = calculate_accrual_amount_for_loans(
			loan,
			posting_date=posting_date if payment_type == "Loan Closure" else add_days(posting_date, -1),
			accrual_type="Regular",
			is_future_accrual=1,
			loan_disbursement=loan_disbursement,
		)

		amounts["unbooked_penalty"] = calculate_penal_interest_for_loans(
			loan=loan, posting_date=posting_date, is_future_accrual=1, loan_disbursement=loan_disbursement
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
	from lending.loan_management.doctype.loan_repayment.utils import (
		get_disbursement_map,
		get_last_demand_date,
		get_pending_principal_amount_for_loans,
		get_unbooked_interest_for_loans,
		process_amount_for_bulk_loans,
	)

	last_demand_date = get_last_demand_date(posting_date, loan=loans[0])

	loan_details = frappe.db.get_all(
		"Loan",
		fields=[
			"name",
			"repayment_schedule_type",
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

	disbursement_map = get_disbursement_map(loan_details)
	principal_amount_map = get_pending_principal_amount_for_loans(loan_details, disbursement_map)
	unbooked_interest_map = get_unbooked_interest_for_loans(
		loan_details, posting_date, last_demand_date=last_demand_date
	)
	loan_demands = get_all_demands(loans, posting_date)

	demand_map = {}
	for loan in loan_demands:
		demand_map.setdefault(loan.loan, [])
		demand_map[loan.loan].append(loan)

	# Get unbooked interest for all loans

	due_details = []
	for loan in loan_details:
		if loan.repayment_schedule_type == "Line of Credit":
			demands = demand_map.get(loan.name, [])
			for disbursement in disbursement_map.get(loan.name, []):
				amounts = init_amounts()
				principal_amount = principal_amount_map.get((loan.name, disbursement), 0)
				unbooked_interest = unbooked_interest_map.get((loan.name, disbursement), 0)
				filtered_demands = list(d for d in demands if d.loan_disbursement == disbursement)
				amounts = process_amount_for_bulk_loans(
					loan, filtered_demands, disbursement, principal_amount, unbooked_interest, amounts
				)
				due_details.append(amounts)
		else:
			amounts = init_amounts()
			principal_amount = principal_amount_map.get(loan.name, 0)
			unbooked_interest = unbooked_interest_map.get(loan.name, 0)
			demands = demand_map.get(loan.name, [])
			amounts = process_amount_for_bulk_loans(
				loan, demands, None, principal_amount, unbooked_interest, amounts
			)
			due_details.append(amounts)

	return due_details


def get_all_demands(loans, posting_date):
	loan_demand = frappe.qb.DocType("Loan Demand")

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	query = get_demand_query()
	query = (
		query.where(loan_demand.docstatus == 1)
		.where(loan_demand.loan.isin(loans))
		.where(loan_demand.demand_date <= posting_date)
		.where(Round(loan_demand.outstanding_amount, precision) > 0)
	)

	return query.run(as_dict=1)


@frappe.whitelist()
def calculate_amounts(
	against_loan,
	posting_date,
	payment_type="",
	with_loan_details=False,
	charges=None,
	loan_disbursement=None,
	for_update=False,
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
			loan_disbursement=loan_disbursement,
			for_update=for_update,
		)
	else:
		amounts = get_amounts(
			amounts,
			against_loan,
			posting_date,
			payment_type=payment_type,
			charges=charges,
			loan_disbursement=loan_disbursement,
			for_update=for_update,
		)

	amounts["available_security_deposit"] = frappe.db.get_value(
		"Loan Security Deposit", {"loan": against_loan}, "sum(available_amount)"
	)

	# update values for closure
	if payment_type in ("Loan Closure", "Full Settlement", "Write Off Settlement"):
		amounts["payable_principal_amount"] = amounts["pending_principal_amount"]
		amounts["interest_amount"] = (
			amounts["interest_amount"] + amounts["unbooked_interest"] + amounts["unaccrued_interest"]
		)
		amounts["penalty_amount"] = amounts["penalty_amount"] + amounts["unbooked_penalty"]
		amounts["payable_amount"] = (
			amounts["payable_principal_amount"]
			+ amounts["interest_amount"]
			+ amounts["penalty_amount"]
			+ amounts.get("total_charges_payable", 0)
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


def update_installment_counts(against_loan, loan_disbursement=None):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	loan_demand = frappe.qb.DocType("Loan Demand")
	query = (
		frappe.qb.from_(loan_demand)
		.select(
			loan_demand.repayment_schedule_detail,
			Sum(loan_demand.outstanding_amount).as_("total_outstanding_amount"),
		)
		.where(
			(loan_demand.loan == against_loan)
			& (loan_demand.docstatus == 1)
			& (loan_demand.demand_type == "EMI")
		)
		.groupby(
			loan_demand.repayment_schedule_detail,
			loan_demand.demand_date,
		)
	)

	if loan_disbursement:
		query = query.where(loan_demand.loan_disbursement == loan_disbursement)

	loan_demands = query.run(as_dict=1)

	total_installments_raised = 0
	total_installments_paid = 0
	total_installments_overdue = 0

	for demand in loan_demands:
		total_installments_raised += 1
		if flt(demand.total_outstanding_amount, precision) <= 0:
			total_installments_paid += 1
		else:
			total_installments_overdue += 1

	schedule_filters = {
		"loan": against_loan,
		"docstatus": 1,
		"status": "Active",
	}

	if loan_disbursement:
		schedule_filters["loan_disbursement"] = loan_disbursement

	schedule = frappe.db.get_value("Loan Repayment Schedule", schedule_filters, "name")

	frappe.db.set_value(
		"Loan Repayment Schedule",
		schedule,
		{
			"total_installments_raised": total_installments_raised,
			"total_installments_paid": total_installments_paid,
			"total_installments_overdue": total_installments_overdue,
		},
	)


def get_last_demand_date(
	loan, posting_date, demand_subtype="Interest", loan_disbursement=None, status=None
):
	from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
		get_last_disbursement_date,
	)

	filters = {
		"loan": loan,
		"docstatus": 1,
		"demand_subtype": demand_subtype,
		"demand_date": ("<=", posting_date),
	}

	if loan_disbursement:
		filters["loan_disbursement"] = loan_disbursement

	last_demand_date = frappe.db.get_value(
		"Loan Demand",
		filters,
		"MAX(demand_date)",
	)

	if demand_subtype == "Interest" and last_demand_date and status != "Closed":
		last_demand_date = add_days(last_demand_date, -1)

	if not last_demand_date:
		last_demand_date = get_last_disbursement_date(
			loan, posting_date, loan_disbursement=loan_disbursement
		)

	return last_demand_date


def get_latest_accrual_date(loan, posting_date, interest_type="Interest", loan_disbursement=None):
	filters = {
		"loan": loan,
		"docstatus": 1,
		"interest_type": interest_type,
		"posting_date": (">", posting_date),
	}

	if loan_disbursement:
		filters["loan_disbursement"] = loan_disbursement

	latest_accrual_date = frappe.db.get_value(
		"Loan Interest Accrual",
		filters,
		"MAX(posting_date)",
	)

	return latest_accrual_date


def get_unbooked_interest(loan, posting_date, loan_disbursement=None, last_demand_date=None):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	accrued_interest = get_accrued_interest(
		loan, posting_date, loan_disbursement=loan_disbursement, last_demand_date=last_demand_date
	)
	unbooked_interest = flt(accrued_interest, precision)

	return unbooked_interest, accrued_interest


def get_accrued_interest(
	loan, posting_date, interest_type="Normal Interest", last_demand_date=None, loan_disbursement=None
):
	filters = [
		["loan", "=", loan],
		["docstatus", "=", 1],
		["posting_date", "<", posting_date],
		["interest_type", "=", interest_type],
	]

	if last_demand_date:
		filters.append(["posting_date", ">", last_demand_date])

	if loan_disbursement:
		filters.append(["loan_disbursement", "=", loan_disbursement])

	accrued_interest = frappe.db.get_value(
		"Loan Interest Accrual",
		filters,
		"SUM(interest_amount)",
	)

	return flt(accrued_interest)


def get_demanded_interest(loan, posting_date, demand_subtype="Interest", loan_disbursement=None):
	filters = {
		"loan": loan,
		"docstatus": 1,
		"demand_date": ("<=", posting_date),
		"demand_subtype": demand_subtype,
	}

	if loan_disbursement:
		filters["loan_disbursement"] = loan_disbursement

	demand_interest = frappe.db.get_value(
		"Loan Demand",
		filters,
		"SUM(demand_amount)",
	)

	return flt(demand_interest)


def get_net_paid_amount(loan):
	return frappe.db.get_value("Loan", {"name": loan}, "sum(total_amount_paid - refund_amount)")
