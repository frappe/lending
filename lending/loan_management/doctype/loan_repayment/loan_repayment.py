# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_datetime, getdate

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan.loan import update_all_linked_loan_customer_npa_status
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	get_last_accrual_date,
	get_per_day_interest,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)
from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
	create_process_loan_classification,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_demand_loans,
)


class LoanRepayment(AccountsController):
	def validate(self):
		amounts = calculate_amounts(self.against_loan, self.posting_date)
		self.add_pending_charges()
		self.set_missing_values(amounts)
		self.check_future_entries()
		self.validate_amount()
		self.allocate_amounts(amounts)

	def before_submit(self):
		self.book_unaccrued_interest()

	def on_submit(self):
		if self.repayment_type == "Normal Repayment":

			create_process_loan_classification(
				posting_date=self.posting_date,
				loan_product=self.loan_product,
				loan=self.against_loan,
				payment_reference=self.name,
			)

		# self.update_repayment_schedule()
		self.update_paid_amount()
		if self.repayment_type == "Charges Waiver":
			self.make_credit_note()

		self.make_gl_entries()

	def on_cancel(self):
		self.check_future_accruals()
		# self.update_repayment_schedule(cancel=1)
		if self.repayment_type == "Normal Repayment":
			self.mark_as_unpaid()
			if self.is_npa or self.manual_npa:
				# Mark back all loans as NPA
				update_all_linked_loan_customer_npa_status(
					self.is_npa, self.manual_npa, self.applicant_type, self.applicant
				)

			frappe.db.set_value("Loan", self.against_loan, "days_past_due", self.days_past_due)

		self.ignore_linked_doctypes = [
			"GL Entry",
			"Payment Ledger Entry",
			"Process Loan Classification",
		]
		self.make_gl_entries(cancel=1)

	def make_credit_note(self):
		item_details = frappe.db.get_value(
			"Loan Product",
			self.loan_product,
			["charges_waiver_item"],
			as_dict=1,
		)

		charges_waiver_item_income_account = frappe.db.get_value(
			"Loan Charges",
			{"charge_type": item_details.charges_waiver_item, "parent": self.loan_product},
			"income_account",
		)

		for invoice in self.get("pending_charges"):
			if invoice.sales_invoice:
				si = frappe.new_doc("Sales Invoice")
				si.customer = self.applicant
				si.append(
					"items",
					{
						"item_code": item_details.charges_waiver_item,
						"qty": -1,
						"rate": invoice.allocated_amount,
						"income_account": charges_waiver_item_income_account,
					},
				)
				si.set_missing_values()
				si.is_return = 1
				si.loan = self.against_loan
				si.save()
				for tax in si.get("taxes"):
					tax.included_in_print_rate = 1
				si.save()
				si.submit()

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

		if not self.get("pending_charges"):
			for d in amounts.get("charges"):
				self.append(
					{
						"sales_invoice": d.sales_invoice,
						"pending_charge_amount": d.pending_charge_amount,
					}
				)

		self.total_charges_payable = flt(amounts["total_charges_payable"], precision)

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

	def validate_amount(self):
		if not self.amount_paid:
			frappe.throw(_("Amount paid cannot be zero"))

	def book_unaccrued_interest(self):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		if flt(self.total_interest_paid, precision) > flt(self.interest_payable, precision):
			if not self.is_term_loan:
				# get last loan interest accrual date
				last_accrual_date = get_last_accrual_date(self.against_loan, self.posting_date)

				# get posting date upto which interest has to be accrued
				per_day_interest = get_per_day_interest(
					self.pending_principal_amount, self.rate_of_interest, self.company, self.posting_date
				)

				no_of_days = (
					flt(flt(self.total_interest_paid - self.interest_payable, precision) / per_day_interest, 0)
					- 1
				)

				posting_date = add_days(last_accrual_date, no_of_days)

				# book excess interest paid
				process = process_loan_interest_accrual_for_demand_loans(
					posting_date=posting_date, loan=self.against_loan, accrual_type="Repayment"
				)

				# get loan interest accrual to update paid amount
				lia = frappe.db.get_value(
					"Loan Interest Accrual",
					{"process_loan_interest_accrual": process},
					["name", "interest_amount", "payable_principal_amount"],
					as_dict=1,
				)

				if lia:
					self.append(
						"repayment_details",
						{
							"loan_interest_accrual": lia.name,
							"paid_interest_amount": flt(self.total_interest_paid - self.interest_payable, precision),
							"paid_principal_amount": 0.0,
							"accrual_type": "Repayment",
						},
					)

	def add_pending_charges(self):
		self.set("pending_charges", [])
		invoices = get_outstanding_invoices(self.against_loan, self.posting_date)
		for d in invoices:
			self.append(
				"pending_charges",
				{
					"sales_invoice": d.voucher_no,
					"pending_charge_amount": d.outstanding_amount,
				},
			)

	def update_paid_amount(self):
		loan = frappe.get_value(
			"Loan",
			self.against_loan,
			[
				"total_amount_paid",
				"total_principal_paid",
				"status",
				"is_secured_loan",
				"total_payment",
				"debit_adjustment_amount",
				"credit_adjustment_amount",
				"refund_amount",
				"loan_amount",
				"disbursed_amount",
				"total_interest_payable",
				"written_off_amount",
			],
			as_dict=1,
		)

		loan.update(
			{
				"total_amount_paid": loan.total_amount_paid + self.amount_paid,
				"total_principal_paid": loan.total_principal_paid + self.principal_amount_paid,
			}
		)

		pending_principal_amount = get_pending_principal_amount(loan)
		if not loan.is_secured_loan and pending_principal_amount <= 0:
			loan.update({"status": "Loan Closure Requested"})

		for payment in self.repayment_details:
			frappe.db.sql(
				""" UPDATE `tabLoan Interest Accrual`
				SET paid_principal_amount = `paid_principal_amount` + %s,
					paid_interest_amount = `paid_interest_amount` + %s
				WHERE name = %s""",
				(
					flt(payment.paid_principal_amount),
					flt(payment.paid_interest_amount),
					payment.loan_interest_accrual,
				),
			)

		if self.repayment_type == "Normal Repayment":
			frappe.db.sql(
				""" UPDATE `tabLoan`
				SET total_amount_paid = %s, total_principal_paid = %s, status = %s
				WHERE name = %s """,
				(loan.total_amount_paid, loan.total_principal_paid, loan.status, self.against_loan),
			)

			update_shortfall_status(self.against_loan, self.principal_amount_paid)

	def mark_as_unpaid(self):
		loan = frappe.get_value(
			"Loan",
			self.against_loan,
			[
				"total_amount_paid",
				"total_principal_paid",
				"status",
				"is_secured_loan",
				"total_payment",
				"loan_amount",
				"disbursed_amount",
				"total_interest_payable",
				"written_off_amount",
			],
			as_dict=1,
		)

		no_of_repayments = len(self.repayment_details)

		loan.update(
			{
				"total_amount_paid": loan.total_amount_paid - self.amount_paid,
				"total_principal_paid": loan.total_principal_paid - self.principal_amount_paid,
			}
		)

		if loan.status == "Loan Closure Requested":
			if loan.disbursed_amount >= loan.loan_amount:
				loan["status"] = "Disbursed"
			else:
				loan["status"] = "Partially Disbursed"

		for payment in self.repayment_details:
			frappe.db.sql(
				""" UPDATE `tabLoan Interest Accrual`
				SET paid_principal_amount = `paid_principal_amount` - %s,
					paid_interest_amount = `paid_interest_amount` - %s
				WHERE name = %s""",
				(payment.paid_principal_amount, payment.paid_interest_amount, payment.loan_interest_accrual),
			)

			# Cancel repayment interest accrual
			# checking idx as a preventive measure, repayment accrual will always be the last entry
			if payment.accrual_type == "Repayment" and payment.idx == no_of_repayments:
				lia_doc = frappe.get_doc("Loan Interest Accrual", payment.loan_interest_accrual)
				lia_doc.cancel()

		frappe.db.sql(
			""" UPDATE `tabLoan`
			SET total_amount_paid = %s, total_principal_paid = %s, status = %s
			WHERE name = %s """,
			(loan.total_amount_paid, loan.total_principal_paid, loan.status, self.against_loan),
		)

	def check_future_accruals(self):
		if self.is_term_loan:
			return

		future_accrual_date = frappe.db.get_value(
			"Loan Interest Accrual",
			{"due_date": (">", self.posting_date), "docstatus": 1, "loan": self.against_loan},
			"due_date",
		)

		if future_accrual_date:
			frappe.throw(
				"Cannot cancel. Interest accruals already processed till {0}".format(
					get_datetime(future_accrual_date)
				)
			)

	def update_repayment_schedule(self, cancel=0):
		if self.is_term_loan and self.principal_amount_paid > self.payable_principal_amount:
			regenerate_repayment_schedule(self.against_loan, cancel)

	def allocate_amounts(self, repayment_details):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		self.set("repayment_details", [])
		self.principal_amount_paid = 0
		self.total_penalty_paid = 0
		interest_paid = self.amount_paid

		if self.shortfall_amount and self.amount_paid > self.shortfall_amount:
			self.principal_amount_paid = self.shortfall_amount
		elif self.shortfall_amount:
			self.principal_amount_paid = self.amount_paid

		interest_paid -= self.principal_amount_paid

		if interest_paid > 0 and not self.is_term_loan:
			if self.penalty_amount and interest_paid > self.penalty_amount:
				self.total_penalty_paid = flt(self.penalty_amount, precision)
			elif self.penalty_amount:
				self.total_penalty_paid = flt(interest_paid, precision)

			interest_paid -= self.total_penalty_paid

			interest_paid, updated_entries = self.allocate_interest_amount(
				interest_paid, repayment_details, {}
			)
			self.allocate_excess_payment_for_demand_loans(interest_paid, repayment_details)

		if self.is_term_loan:
			if self.repayment_type == "Normal Repayment":
				if self.offset_based_on_npa:
					self.offset_repayment_based_on_npa(interest_paid, repayment_details)
				else:
					interest_paid, updated_entries = self.allocate_interest_amount(
						interest_paid, repayment_details
					)
					self.allocate_principal_amount_for_term_loans(
						interest_paid, repayment_details, updated_entries
					)
			elif self.repayment_type in ("Principal Adjustment", "Principal Capitalization"):
				self.allocate_principal_amount_for_term_loans(interest_paid, repayment_details, {})
			elif self.repayment_type in (
				"Interest Waiver",
				"Interest Capitalization",
				"Interest Adjustment",
				"Interest Carry Forward",
			):
				self.allocate_interest_amount(interest_paid, repayment_details)
			elif self.repayment_type in ("Penalty Waiver", "Penalty Capitalization"):
				self.allocate_penalty(interest_paid)
			elif self.repayment_type in ("Charges Waiver", "Charges Capitalization"):
				self.allocate_charges(interest_paid)

	def offset_repayment_based_on_npa(self, interest_paid, repayment_details):
		if interest_paid > 0:
			offset_base_on = frappe.db.get_value(
				"Company",
				self.company,
				[
					"collection_offset_logic_based_on",
					"days_past_due_threshold",
					"collection_offset_sequence_for_standard_asset",
					"collection_offset_sequence_for_sub_standard_asset",
				],
				as_dict=1,
			)

			if (
				offset_base_on.collection_offset_logic_based_on == "NPA Flag"
				and (self.is_npa or self.manual_npa)
			) or (
				offset_base_on.collection_offset_logic_based_on == "Days Past Due"
				and self.days_past_due > cint(offset_base_on.days_past_due_threshold)
			):
				if offset_base_on.collection_offset_sequence_for_sub_standard_asset == "PPP...III...CCC":
					self.allocate_as_per_npa(interest_paid, repayment_details)
				else:
					self.allocate_as_per_non_npa(interest_paid, repayment_details)
			else:
				if offset_base_on.collection_offset_sequence_for_standard_asset == "IP...IP...IP...CCC":
					self.allocate_as_per_non_npa(interest_paid, repayment_details)
				else:
					self.allocate_as_per_npa(interest_paid, repayment_details)

	def allocate_as_per_non_npa(self, interest_paid, repayment_details):
		self.total_interest_paid = 0
		for lia, amounts in repayment_details.get("pending_accrual_entries", []).items():
			interest_amount = 0
			principal_amount = 0
			if amounts["interest_amount"] <= interest_paid:
				interest_amount = amounts["interest_amount"]
				interest_paid -= interest_amount
				self.total_interest_paid += amounts["interest_amount"]
				if amounts["payable_principal_amount"] <= interest_paid:
					principal_amount = amounts["payable_principal_amount"]
					interest_paid -= principal_amount
					self.principal_amount_paid += principal_amount
				elif interest_paid:
					principal_amount = interest_paid
					interest_paid = 0
					self.principal_amount_paid += principal_amount
			elif interest_paid:
				interest_amount = interest_paid
				interest_paid = 0
				self.total_interest_paid += interest_amount

			if interest_amount or principal_amount:
				self.append(
					"repayment_details",
					{
						"loan_interest_accrual": lia,
						"paid_principal_amount": principal_amount,
						"paid_interest_amount": interest_amount,
					},
				)
		interest_paid = self.allocate_penalty(interest_paid)
		self.allocate_charges(interest_paid)

	def allocate_as_per_npa(self, interest_paid, repayment_details):
		interest_paid, updated_entries = self.allocate_principal_amount_for_term_loans(
			interest_paid, repayment_details, {}
		)
		interest_paid, updated_entries = self.allocate_interest_amount(
			interest_paid, repayment_details, updated_entries
		)
		interest_paid = self.allocate_penalty(interest_paid)
		self.allocate_charges(interest_paid)

	def allocate_interest_amount(self, interest_paid, repayment_details, updated_entries=None):
		self.total_interest_paid = 0
		idx = 1
		if not updated_entries:
			updated_entries = {}

		if interest_paid > 0:
			for lia, amounts in repayment_details.get("pending_accrual_entries", []).items():
				interest_amount = 0
				if amounts["interest_amount"] <= interest_paid:
					interest_amount = amounts["interest_amount"]
					self.total_interest_paid += interest_amount
					interest_paid -= interest_amount
				elif interest_paid:
					if interest_paid >= amounts["interest_amount"]:
						interest_amount = amounts["interest_amount"]
						self.total_interest_paid += interest_amount
						interest_paid = 0
					else:
						interest_amount = interest_paid
						self.total_interest_paid += interest_amount
						interest_paid = 0

				if updated_entries.get(lia):
					idx = updated_entries.get(lia)
					self.get("repayment_details")[idx - 1].paid_interest_amount += interest_amount
				if interest_amount:
					self.append(
						"repayment_details",
						{
							"loan_interest_accrual": lia,
							"paid_interest_amount": interest_amount,
							"paid_principal_amount": 0,
						},
					)
					updated_entries[lia] = idx
					idx += 1

		return interest_paid, updated_entries

	def allocate_principal_amount_for_term_loans(
		self, interest_paid, repayment_details, updated_entries
	):
		if interest_paid > 0:
			for lia, amounts in repayment_details.get("pending_accrual_entries", []).items():
				paid_principal = 0
				if amounts["payable_principal_amount"] <= interest_paid:
					paid_principal = amounts["payable_principal_amount"]
					self.principal_amount_paid += paid_principal
					interest_paid -= paid_principal
				elif interest_paid:
					if interest_paid >= amounts["payable_principal_amount"]:
						paid_principal = amounts["payable_principal_amount"]
						self.principal_amount_paid += paid_principal
						interest_paid = 0
					else:
						paid_principal = interest_paid
						self.principal_amount_paid += paid_principal
						interest_paid = 0

				if updated_entries.get(lia):
					idx = updated_entries.get(lia)
					self.get("repayment_details")[idx - 1].paid_principal_amount += paid_principal
				else:
					self.append(
						"repayment_details",
						{
							"loan_interest_accrual": lia,
							"paid_interest_amount": 0,
							"paid_principal_amount": paid_principal,
						},
					)

		return interest_paid, updated_entries

	def allocate_penalty(self, interest_paid):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		if interest_paid > 0:
			if self.penalty_amount and interest_paid > self.penalty_amount:
				self.total_penalty_paid = flt(self.penalty_amount, precision)
				interest_paid -= self.penalty_amount
			elif self.penalty_amount:
				self.total_penalty_paid = flt(interest_paid, precision)
				interest_paid = 0

		return interest_paid

	def allocate_charges(self, interest_paid):
		precision = cint(frappe.db.get_default("currency_precision")) or 2
		self.total_paid_charges = 0
		if interest_paid > 0:
			for charge in self.get("pending_charges"):
				charge.allocated_amount = 0
				if charge.pending_charge_amount and interest_paid > charge.pending_charge_amount:
					charge.allocated_amount = charge.pending_charge_amount
					interest_paid -= charge.pending_charge_amount
					self.total_paid_charges += charge.allocated_amount
				elif charge.pending_charge_amount:
					charge.allocated_amount = interest_paid
					interest_paid = 0
					self.total_paid_charges += charge.allocated_amount

				charge.allocated_amount = flt(charge.allocated_amount, precision)

	def allocate_excess_payment_for_demand_loans(self, interest_paid, repayment_details):
		if repayment_details["unaccrued_interest"] and interest_paid > 0:
			# no of days for which to accrue interest
			# Interest can only be accrued for an entire day and not partial
			if interest_paid > repayment_details["unaccrued_interest"]:
				interest_paid -= repayment_details["unaccrued_interest"]
				self.total_interest_paid += repayment_details["unaccrued_interest"]
			else:
				# get no of days for which interest can be paid
				per_day_interest = get_per_day_interest(
					self.pending_principal_amount, self.rate_of_interest, self.company, self.posting_date
				)

				no_of_days = cint(interest_paid / per_day_interest)
				self.total_interest_paid += no_of_days * per_day_interest
				interest_paid -= no_of_days * per_day_interest

		if interest_paid > 0:
			self.principal_amount_paid += interest_paid

	def make_gl_entries(self, cancel=0, adv_adj=0):
		gle_map = []
		remarks = self.get_remarks()
		payment_account = self.get_payment_account()

		payment_party_type = ""
		payment_party = ""

		if (
			hasattr(self, "process_payroll_accounting_entry_based_on_employee")
			and self.process_payroll_accounting_entry_based_on_employee
		):
			payment_party_type = "Employee"
			payment_party = self.applicant

		account_details = frappe.db.get_value(
			"Loan Product",
			self.loan_product,
			[
				"interest_receivable_account",
				"suspense_interest_receivable",
				"suspense_interest_income",
				"interest_income_account",
			],
			as_dict=1,
		)

		if self.total_penalty_paid:
			penalty_receivable_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "penalty_receivable_account"
			)
			gle_map.append(
				self.get_gl_dict(
					{
						"account": payment_account,
						"against": penalty_receivable_account,
						"debit": self.total_penalty_paid,
						"debit_in_account_currency": self.total_penalty_paid,
						"against_voucher_type": "Loan",
						"against_voucher": self.against_loan,
						"remarks": _("Penalty against loan:") + self.against_loan,
						"cost_center": self.cost_center,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"posting_date": getdate(self.posting_date),
					}
				)
			)

			gle_map.append(
				self.get_gl_dict(
					{
						"account": penalty_receivable_account,
						"against": payment_account,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"credit": self.total_penalty_paid,
						"credit_in_account_currency": self.total_penalty_paid,
						"against_voucher_type": "Loan",
						"against_voucher": self.against_loan,
						"remarks": _("Penalty against loan:") + self.against_loan,
						"cost_center": self.cost_center,
						"posting_date": getdate(self.posting_date),
					}
				)
			)

		for repayment in self.get("repayment_details"):
			if repayment.paid_interest_amount:
				gle_map.append(
					self.get_gl_dict(
						{
							"account": payment_account,
							"against": account_details.interest_receivable_account + ", " + self.penalty_income_account,
							"debit": repayment.paid_interest_amount,
							"debit_in_account_currency": repayment.paid_interest_amount,
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

				gle_map.append(
					self.get_gl_dict(
						{
							"account": account_details.interest_receivable_account,
							"party_type": self.applicant_type,
							"party": self.applicant,
							"against": payment_account,
							"credit": repayment.paid_interest_amount,
							"credit_in_account_currency": repayment.paid_interest_amount,
							"against_voucher_type": "Loan",
							"against_voucher": self.against_loan,
							"remarks": _(remarks),
							"cost_center": self.cost_center,
							"posting_date": getdate(self.posting_date),
						}
					)
				)

				if self.is_npa:
					gle_map.append(
						self.get_gl_dict(
							{
								"account": account_details.interest_receivable_account,
								"against": account_details.suspense_interest_receivable,
								"party_type": self.applicant_type,
								"party": self.applicant,
								"debit": repayment.paid_interest_amount,
								"debit_in_account_currency": repayment.paid_interest_amount,
								"against_voucher_type": "Loan",
								"against_voucher": self.against_loan,
								"cost_center": self.cost_center,
								"posting_date": getdate(self.posting_date),
							}
						)
					)

					gle_map.append(
						self.get_gl_dict(
							{
								"account": account_details.suspense_interest_receivable,
								"party_type": self.applicant_type,
								"party": self.applicant,
								"against": account_details.interest_receivable_account,
								"credit": repayment.paid_interest_amount,
								"credit_in_account_currency": repayment.paid_interest_amount,
								"against_voucher_type": "Loan",
								"against_voucher": self.against_loan,
								"cost_center": self.cost_center,
								"posting_date": getdate(self.posting_date),
							}
						)
					)

					gle_map.append(
						self.get_gl_dict(
							{
								"account": account_details.interest_income_account,
								"credit_in_account_currency": repayment.paid_interest_amount,
								"credit": repayment.paid_interest_amount,
								"cost_center": self.cost_center,
								"against": account_details.suspense_interest_income,
							}
						)
					)

					gle_map.append(
						self.get_gl_dict(
							{
								"account": account_details.suspense_interest_income,
								"debit": repayment.paid_interest_amount,
								"debit_in_account_currency": repayment.paid_interest_amount,
								"cost_center": self.cost_center,
								"against": account_details.interest_income_account,
							}
						)
					)

			if repayment.paid_principal_amount:
				gle_map.append(
					self.get_gl_dict(
						{
							"account": payment_account,
							"against": account_details.interest_receivable_account + ", " + self.penalty_income_account,
							"debit": repayment.paid_principal_amount,
							"debit_in_account_currency": repayment.paid_principal_amount,
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

				gle_map.append(
					self.get_gl_dict(
						{
							"account": self.loan_account,
							"party_type": self.applicant_type,
							"party": self.applicant,
							"against": payment_account,
							"credit": repayment.paid_principal_amount,
							"credit_in_account_currency": repayment.paid_principal_amount,
							"against_voucher_type": "Loan",
							"against_voucher": self.against_loan,
							"remarks": _(remarks),
							"cost_center": self.cost_center,
							"posting_date": getdate(self.posting_date),
						}
					)
				)

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj, merge_entries=False)

	def get_payment_account(self):
		payment_account_field_map = {
			"Interest Waiver": "interest_waiver_account",
			"Penalty Waiver": "penalty_waiver_account",
			"Charges Waiver": "charges_waiver_account",
			"Principal Capitalization": "loan_account",
			"Interest Capitalization": "loan_account",
			"Charges Capitalization": "loan_account",
			"Penalty Capitalization": "loan_account",
			"Principal Adjustment": "security_deposit_account",
			"Interest Adjustment": "security_deposit_account",
			"Interest Carry Forward": "interest_income_account",
		}

		if self.repayment_type == "Normal Repayment":
			if hasattr(self, "repay_from_salary") and self.repay_from_salary:
				payment_account = self.payroll_payable_account
			else:
				payment_account = self.payment_account
		else:
			payment_account = frappe.db.get_value(
				"Loan Product", self.loan_product, payment_account_field_map.get(self.repayment_type)
			)

		return payment_account

	def get_remarks(self):
		if self.shortfall_amount and self.amount_paid > self.shortfall_amount:
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


def get_accrued_interest_entries(against_loan, posting_date=None):
	if not posting_date:
		posting_date = getdate()

	precision = cint(frappe.db.get_default("currency_precision")) or 2

	unpaid_accrued_entries = frappe.db.sql(
		"""
			SELECT name, due_date, interest_amount - paid_interest_amount as interest_amount,
				payable_principal_amount - paid_principal_amount as payable_principal_amount,
				accrual_type
			FROM
				`tabLoan Interest Accrual`
			WHERE
				loan = %s
			AND due_date <= %s
			AND (interest_amount - paid_interest_amount > 0 OR
				payable_principal_amount - paid_principal_amount > 0)
			AND
				docstatus = 1
			ORDER BY due_date
		""",
		(against_loan, posting_date),
		as_dict=1,
	)

	# Skip entries with zero interest amount & payable principal amount
	unpaid_accrued_entries = [
		d
		for d in unpaid_accrued_entries
		if flt(d.interest_amount, precision) > 0 or flt(d.payable_principal_amount, precision) > 0
	]

	return unpaid_accrued_entries


def get_penalty_details(against_loan):
	penalty_details = frappe.db.sql(
		"""
		SELECT posting_date, sum(penalty_amount - total_penalty_paid) as pending_penalty_amount
		FROM `tabLoan Repayment` where posting_date >= (SELECT MAX(posting_date) from `tabLoan Repayment`
		where against_loan = %s) and docstatus = 1 and against_loan = %s
	""",
		(against_loan, against_loan),
	)

	if penalty_details:
		return penalty_details[0][0], flt(penalty_details[0][1])
	else:
		return None, 0


def regenerate_repayment_schedule(loan, cancel=0):
	from lending.loan_management.doctype.loan.loan import (
		add_single_month,
		get_monthly_repayment_amount,
	)

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	loan_doc = frappe.get_doc("Loan", loan)
	next_accrual_date = None
	accrued_entries = 0
	last_repayment_amount = None
	last_balance_amount = None

	original_repayment_schedule_len = len(loan_doc.get("repayment_schedule"))

	for term in reversed(loan_doc.get("repayment_schedule")):
		if not term.is_accrued:
			next_accrual_date = term.payment_date
			loan_doc.remove(term)
		else:
			accrued_entries += 1
			if last_repayment_amount is None:
				last_repayment_amount = term.total_payment
			if last_balance_amount is None:
				last_balance_amount = term.balance_loan_amount

	loan_doc.save()

	balance_amount = get_pending_principal_amount(loan_doc)

	if loan_doc.repayment_method == "Repay Fixed Amount per Period":
		monthly_repayment_amount = flt(
			balance_amount / (original_repayment_schedule_len - accrued_entries)
		)
	else:
		repayment_period = loan_doc.repayment_periods - accrued_entries
		if not cancel and repayment_period > 0:
			monthly_repayment_amount = get_monthly_repayment_amount(
				balance_amount, loan_doc.rate_of_interest, repayment_period
			)
		else:
			monthly_repayment_amount = last_repayment_amount
			balance_amount = last_balance_amount

	payment_date = next_accrual_date

	while flt(balance_amount, precision) > 0:
		interest_amount = flt(balance_amount * flt(loan_doc.rate_of_interest) / (12 * 100))
		principal_amount = monthly_repayment_amount - interest_amount
		balance_amount = flt(balance_amount + interest_amount - monthly_repayment_amount)
		if balance_amount < 0:
			principal_amount += balance_amount
			balance_amount = 0.0

		total_payment = principal_amount + interest_amount
		loan_doc.append(
			"repayment_schedule",
			{
				"payment_date": payment_date,
				"principal_amount": principal_amount,
				"interest_amount": interest_amount,
				"total_payment": total_payment,
				"balance_loan_amount": balance_amount,
			},
		)
		next_payment_date = add_single_month(payment_date)
		payment_date = next_payment_date

	loan_doc.save()


def get_pending_principal_amount(loan):
	if loan.status in ("Disbursed", "Closed") or loan.disbursed_amount >= loan.loan_amount:
		pending_principal_amount = (
			flt(loan.total_payment)
			+ flt(loan.debit_adjustment_amount)
			- flt(loan.credit_adjustment_amount)
			- flt(loan.total_principal_paid)
			- flt(loan.total_interest_payable)
			- flt(loan.written_off_amount)
			+ flt(loan.refund_amount)
		)
	else:
		pending_principal_amount = (
			flt(loan.disbursed_amount)
			+ flt(loan.debit_adjustment_amount)
			- flt(loan.credit_adjustment_amount)
			- flt(loan.total_principal_paid)
			- flt(loan.total_interest_payable)
			- flt(loan.written_off_amount)
			+ flt(loan.refund_amount)
		)

	return pending_principal_amount


# This function returns the amounts that are payable at the time of loan repayment based on posting date
# So it pulls all the unpaid Loan Interest Accrual Entries and calculates the penalty if applicable


def get_amounts(amounts, against_loan, posting_date, with_loan_details=False):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	against_loan_doc = frappe.get_doc("Loan", against_loan)
	loan_product_details = frappe.get_doc("Loan Product", against_loan_doc.loan_product)
	accrued_interest_entries = get_accrued_interest_entries(against_loan_doc.name, posting_date)

	computed_penalty_date, pending_penalty_amount = get_penalty_details(against_loan)
	pending_accrual_entries = {}

	if against_loan_doc.is_term_loan:
		pending_penalty_amount = 0
		computed_penalty_date = None

	total_pending_interest = 0
	penalty_amount = 0
	payable_principal_amount = 0
	final_due_date = ""
	last_entry_due_date = ""

	for entry in accrued_interest_entries:
		# Loan repayment due date is one day after the loan interest is accrued
		# no of late days are calculated based on loan repayment posting date
		# and if no_of_late days are positive then penalty is levied

		due_date_after_grace_period = add_days(entry.due_date, loan_product_details.grace_period_in_days)

		if computed_penalty_date and getdate(computed_penalty_date) >= getdate(
			due_date_after_grace_period
		):
			due_date_after_grace_period = computed_penalty_date

		no_of_late_days = date_diff(posting_date, due_date_after_grace_period)

		if (
			no_of_late_days > 0
			and (
				not (hasattr(against_loan_doc, "repay_from_salary") and against_loan_doc.repay_from_salary)
			)
			and entry.accrual_type == "Regular"
		):
			penalty_amount += (
				(entry.interest_amount + entry.payable_principal_amount)
				* (loan_product_details.penalty_interest_rate / 100)
				* no_of_late_days
			) / 365

		total_pending_interest += entry.interest_amount
		payable_principal_amount += entry.payable_principal_amount

		pending_accrual_entries.setdefault(
			entry.name,
			{
				"interest_amount": flt(entry.interest_amount, precision),
				"payable_principal_amount": flt(entry.payable_principal_amount, precision),
			},
		)

		last_entry_due_date = entry.due_date
		if entry.due_date and not final_due_date:
			final_due_date = add_days(entry.due_date, loan_product_details.grace_period_in_days)

	pending_principal_amount = get_pending_principal_amount(against_loan_doc)

	unaccrued_interest = 0
	pending_days = date_diff(posting_date, last_entry_due_date)

	if pending_days > 0:
		if against_loan_doc.is_term_loan:
			principal_amount = flt(pending_principal_amount - payable_principal_amount, precision)
		else:
			principal_amount = flt(pending_principal_amount, precision)

		per_day_interest = get_per_day_interest(
			principal_amount,
			loan_product_details.rate_of_interest,
			loan_product_details.company,
			posting_date,
		)
		unaccrued_interest += pending_days * per_day_interest

	amounts["pending_principal_amount"] = flt(pending_principal_amount, precision)
	amounts["payable_principal_amount"] = flt(payable_principal_amount, precision)
	amounts["interest_amount"] = flt(total_pending_interest, precision)
	amounts["penalty_amount"] = flt(penalty_amount + pending_penalty_amount, precision)
	amounts["payable_amount"] = flt(
		payable_principal_amount + total_pending_interest + penalty_amount, precision
	)
	amounts["pending_accrual_entries"] = pending_accrual_entries
	amounts["unaccrued_interest"] = flt(unaccrued_interest, precision)
	amounts["written_off_amount"] = flt(against_loan_doc.written_off_amount, precision)

	if final_due_date:
		amounts["due_date"] = final_due_date

	if with_loan_details:
		return amounts, against_loan_doc.as_dict()
	else:
		return amounts


@frappe.whitelist()
def calculate_amounts(against_loan, posting_date, payment_type="", with_loan_details=False):
	amounts = {
		"penalty_amount": 0.0,
		"interest_amount": 0.0,
		"pending_principal_amount": 0.0,
		"payable_principal_amount": 0.0,
		"payable_amount": 0.0,
		"unaccrued_interest": 0.0,
		"due_date": "",
		"total_charges_payable": 0.0,
		"available_security_deposit": 0.0,
	}

	if with_loan_details:
		amounts, loan_details = get_amounts(amounts, against_loan, posting_date, with_loan_details)
	else:
		amounts = get_amounts(amounts, against_loan, posting_date)

	charges = []
	invoices = get_outstanding_invoices(against_loan, posting_date)
	for d in invoices:
		charges.append(
			{
				"sales_invoice": d.voucher_no,
				"pending_charge_amount": d.outstanding_amount,
			}
		)
		amounts["total_charges_payable"] += d.outstanding_amount

	amounts["charges"] = charges
	amounts["payable_amount"] += amounts["total_charges_payable"]
	amounts["available_security_deposit"] = frappe.db.get_value(
		"Loan Security Deposit", {"loan": against_loan}, "sum(deposit_amount - allocated_amount)"
	)

	# update values for closure
	if payment_type == "Loan Closure":
		amounts["payable_principal_amount"] = amounts["pending_principal_amount"]
		amounts["interest_amount"] += amounts["unaccrued_interest"]
		amounts["payable_amount"] = (
			amounts["payable_principal_amount"] + amounts["interest_amount"] + amounts["penalty_amount"]
		)

	if with_loan_details:
		return {"amounts": amounts, "loan_details": loan_details}
	else:
		return amounts


def get_outstanding_invoices(loan, posting_date):
	return frappe.db.get_all(
		"Sales Invoice",
		filters={
			"loan": loan,
			"outstanding_amount": ("!=", 0),
			"docstatus": 1,
			"due_date": ("<=", posting_date),
		},
		fields=["name as voucher_no", "outstanding_amount"],
	)
