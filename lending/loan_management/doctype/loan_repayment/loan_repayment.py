# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.query_builder.functions import Round, Sum
from frappe.utils import cint, flt, get_datetime, getdate

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan.loan import update_all_linked_loan_customer_npa_status
from lending.loan_management.doctype.loan_limit_change_log.loan_limit_change_log import (
	create_loan_limit_change_log,
)
from lending.loan_management.doctype.loan_security_assignment.loan_security_assignment import (
	update_loan_securities_values,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)

# from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
# 	create_process_loan_classification,
# )


class LoanRepayment(AccountsController):
	def before_validate(self):
		self.set_repayment_account()

	def validate(self):
		amounts = calculate_amounts(
			self.against_loan, self.posting_date, payment_type=self.repayment_type
		)
		self.set_missing_values(amounts)
		self.check_future_entries()
		self.validate_security_deposit_amount()
		self.validate_amount(amounts["payable_amount"])
		self.allocate_amount_against_demands(amounts)

	def on_update(self):
		from lending.loan_management.doctype.loan_restructure.loan_restructure import (
			create_update_loan_reschedule,
		)

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		principal_adjusted = self.get_principal_adjusted()
		if self.repayment_type in ("Advance Payment", "Pre Payment"):
			if not self.is_new() and flt(self.amount_paid, precision) > flt(self.payable_amount, precision):
				create_update_loan_reschedule(
					self.against_loan,
					self.posting_date,
					self.name,
					self.repayment_type,
					principal_adjusted,
				)

	def get_principal_adjusted(self):
		demand_principal = sum(
			d.paid_amount for d in self.get("repayment_details") if d.demand_subtype == "Principal"
		)

		return self.principal_amount_paid - demand_principal

	def on_submit(self):
		# if self.repayment_type == "Normal Repayment":
		# 	create_process_loan_classification(
		# 		posting_date=self.posting_date,
		# 		loan_product=self.loan_product,
		# 		loan=self.against_loan,
		# 		payment_reference=self.name,
		# 	)
		from lending.loan_management.doctype.loan_demand.loan_demand import reverse_demands
		from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
			make_sales_invoice_for_charge,
		)
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
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

		if self.repayment_type in ("Advance Payment", "Pre Payment"):
			self.process_reschedule()

		if not self.is_term_loan or self.repayment_type in ("Advance Payment", "Pre Payment"):
			amounts = calculate_amounts(
				self.against_loan, self.posting_date, payment_type=self.repayment_type
			)
			self.allocate_amount_against_demands(amounts, on_submit=True)
			self.db_update_all()

		self.update_paid_amounts()
		self.update_demands()
		self.update_limits()
		self.update_security_deposit_amount()
		update_installment_counts(self.against_loan)

		update_loan_securities_values(self.against_loan, self.principal_amount_paid, self.doctype)
		self.create_loan_limit_change_log()
		self.make_gl_entries()

		if self.is_term_loan:
			reverse_loan_interest_accruals(
				self.against_loan, self.posting_date, interest_type="Penal Interest"
			)
			reverse_demands(self.against_loan, self.posting_date, demand_type="Penalty")

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
		loan_restructure.save()
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

		if self.is_npa or self.manual_npa:
			# Mark back all loans as NPA
			update_all_linked_loan_customer_npa_status(
				self.is_npa, self.manual_npa, self.applicant_type, self.applicant
			)

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
		]
		self.make_gl_entries(cancel=1)
		update_installment_counts(self.against_loan)

	def cancel_charge_demands(self):
		sales_invoice = frappe.db.get_value("Sales Invoice", {"loan_repayment": self.name})
		loan_demands = frappe.db.get_all("Loan Demand", {"sales_invoice": sales_invoice}, pluck="name")
		for demand in loan_demands:
			frappe.get_doc("Loan Demand", demand).cancel()

	def cancel_loan_restructure(self):
		loan_restructure = frappe.get_doc("Loan Restructure", {"loan_repayment": self.name})
		loan_restructure.cancel()

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

	def validate_amount(self, payable_amount):
		if not self.amount_paid:
			frappe.throw(_("Amount paid cannot be zero"))

		if self.repayment_type == "Loan Closure" and flt(self.amount_paid) < flt(payable_amount):
			frappe.throw(_("Amount paid cannot be less than payable amount for loan closure"))

	def update_paid_amounts(self):
		if self.repayment_type in ("Normal Repayment", "Pre Payment", "Advance Payment", "Loan Closure"):
			loan = frappe.qb.DocType("Loan")
			query = (
				frappe.qb.update(loan)
				.set(loan.total_amount_paid, loan.total_amount_paid + self.amount_paid)
				.set(loan.total_principal_paid, loan.total_principal_paid + self.principal_amount_paid)
				.where(loan.name == self.against_loan)
			)

			loan_doc = frappe.get_doc("Loan", self.against_loan)
			pending_principal_amount = get_pending_principal_amount(loan_doc)
			is_secured_loan = loan_doc.is_secured_loan

			if not is_secured_loan and pending_principal_amount <= 0:
				query = query.set(loan.status, "Closed")

			query.run()
			update_shortfall_status(self.against_loan, self.principal_amount_paid)

	def mark_as_unpaid(self):
		if self.repayment_type in ("Normal Repayment", "Pre Payment", "Advance Payment", "Loan Closure"):
			loan = frappe.qb.DocType("Loan")

			frappe.qb.update(loan).set(
				loan.total_amount_paid, loan.total_amount_paid - self.amount_paid
			).set(
				loan.total_principal_paid, loan.total_principal_paid - self.principal_amount_paid
			).where(
				loan.name == self.against_loan
			).run()

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
		precision = cint(frappe.db.get_default("currency_precision")) or 2

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

		amount_paid = self.amount_paid

		if self.manual_npa:
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
			if self.is_term_loan:
				if self.get("repayment_type") not in ("Advance Payment", "Pre Payment", "Loan Closure"):
					frappe.throw(_("Amount paid/waived cannot be greater than payable amount"))

				if self.repayment_type == "Advance Payment":
					monthly_repayment_amount = frappe.db.get_value(
						"Loan Repayment Schedule", {"status": "Active", "docstatus": 1}, "monthly_repayment_amount"
					)

					if not (monthly_repayment_amount <= self.amount_paid < (2 * monthly_repayment_amount)):
						frappe.throw(_("Amount for advance payment must be between one to two EMI amount"))

			pending_interest = flt(amounts.get("unaccrued_interest")) + flt(
				amounts.get("unbooked_interest")
			)

			if pending_interest > 0:
				if pending_interest > amount_paid:
					self.total_interest_paid += amount_paid
					amount_paid = 0
				else:
					self.total_interest_paid += pending_interest
					amount_paid -= pending_interest

			self.principal_amount_paid += flt(amount_paid, precision)
			self.total_interest_paid = flt(self.total_interest_paid, precision)
			self.principal_amount_paid = flt(self.principal_amount_paid, precision)
			amount_paid = 0

	def apply_allocation_order(self, allocation_order, pending_amount, demands):
		"""Allocate amount based on allocation order"""
		allocation_order_doc = frappe.get_doc("Loan Demand Offset Order", allocation_order)
		for d in allocation_order_doc.get("components"):
			if d.demand_type == "EMI (Principal + Interest)" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "EMI", demands)
			if d.demand_type == "Principal" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Normal", demands)
			if d.demand_type == "Interest" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Normal", demands)
			if d.demand_type == "Additional Interest" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Additional Interest", demands)
			if d.demand_type == "Penalty" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Penalty", demands)
			if d.demand_type == "Charges" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Charges", demands)

		return pending_amount

	def adjust_component(self, amount_to_adjust, demand_type, demands):
		for demand in demands:
			if demand.demand_type == demand_type:
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
		if cancel:
			make_reverse_gl_entries(voucher_type="Loan Repayment", voucher_no=self.name)
			return

		precision = cint(frappe.db.get_default("currency_precision")) or 2
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
				"penalty_receivable_account",
				"suspense_interest_receivable",
				"suspense_interest_income",
				"interest_income_account",
			],
			as_dict=1,
		)

		if flt(self.principal_amount_paid, precision) > 0:
			against_account = self.loan_account
			gle_map.append(
				self.get_gl_dict(
					{
						"account": payment_account,
						"against": account_details.interest_receivable_account + ", " + self.penalty_income_account,
						"debit": self.principal_amount_paid,
						"debit_in_account_currency": self.principal_amount_paid,
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
						"account": against_account,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"against": payment_account,
						"credit": self.principal_amount_paid,
						"credit_in_account_currency": self.principal_amount_paid,
						"against_voucher_type": "Loan",
						"against_voucher": self.against_loan,
						"remarks": _(remarks),
						"cost_center": self.cost_center,
						"posting_date": getdate(self.posting_date),
					}
				)
			)

		for repayment in self.get("repayment_details"):
			if repayment.demand_subtype == "Principal":
				continue

			if repayment.demand_subtype == "Interest":
				against_account = account_details.interest_receivable_account
			elif repayment.demand_subtype == "Penalty":
				against_account = account_details.penalty_receivable_account
			elif repayment.demand_type == "Charges":
				against_account = frappe.db.get_value("Sales Invoice", repayment.sales_invoice, "debit_to")
				if self.repayment_type == "Charges Waiver":
					payment_account = self.get_charges_waiver_account(self.loan_product, repayment.demand_subtype)

			gle_map.append(
				self.get_gl_dict(
					{
						"account": payment_account,
						"against": account_details.interest_receivable_account + ", " + self.penalty_income_account,
						"debit": repayment.paid_amount,
						"debit_in_account_currency": repayment.paid_amount,
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
						"account": against_account,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"against": payment_account,
						"credit": repayment.paid_amount,
						"credit_in_account_currency": repayment.paid_amount,
						"against_voucher_type": "Sales Invoice" if repayment.sales_invoice else "Loan",
						"against_voucher": repayment.sales_invoice or self.against_loan,
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
							"debit": repayment.paid_amount,
							"debit_in_account_currency": repayment.paid_amount,
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
							"credit": repayment.paid_amount,
							"credit_in_account_currency": repayment.paid_amount,
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
							"credit_in_account_currency": repayment.paid_amount,
							"credit": repayment.paid_amount,
							"cost_center": self.cost_center,
							"against": account_details.suspense_interest_income,
						}
					)
				)

				gle_map.append(
					self.get_gl_dict(
						{
							"account": account_details.suspense_interest_income,
							"debit": repayment.paid_amount,
							"debit_in_account_currency": repayment.paid_amount,
							"cost_center": self.cost_center,
							"against": account_details.interest_income_account,
						}
					)
				)

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj, merge_entries=False)

	def get_payment_account(self):

		if self.repayment_type == "Charges Waiver":
			return

		payment_account_field_map = {
			"Interest Waiver": "interest_waiver_account",
			"Penalty Waiver": "penalty_waiver_account",
			"Principal Capitalization": "loan_account",
			"Loan Closure": "payment_account",
			"Write Off Recovery": "write_off_recovery_account",
			"Principal Adjustment": "loan_account",
			"Interest Adjustment": "security_deposit_account",
			"Interest Carry Forward": "interest_income_account",
			"Security Deposit Adjustment": "security_deposit_account",
			"Subsidy Adjustments": "subsidy_adjustment_account",
		}

		if self.repayment_type in ("Normal Repayment", "Pre Payment", "Advance Payment"):
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


def get_unpaid_demands(
	against_loan, posting_date=None, loan_product=None, demand_type=None, demand_subtype=None, limit=0
):
	if not posting_date:
		posting_date = getdate()

	precision = cint(frappe.db.get_default("currency_precision")) or 2

	loan_demand = frappe.qb.DocType("Loan Demand")
	query = (
		frappe.qb.from_(loan_demand)
		.select(
			loan_demand.name,
			loan_demand.loan,
			loan_demand.demand_date,
			loan_demand.sales_invoice,
			loan_demand.loan_repayment_schedule,
			loan_demand.loan_disbursement,
			loan_demand.loan_product,
			loan_demand.company,
			(loan_demand.outstanding_amount).as_("outstanding_amount"),
			loan_demand.demand_subtype,
			loan_demand.demand_type,
		)
		.where(
			(loan_demand.loan == against_loan)
			& (loan_demand.docstatus == 1)
			& (loan_demand.demand_date <= posting_date)
			& (Round(loan_demand.outstanding_amount, precision) > 0)
		)
		.orderby(loan_demand.demand_date)
		.orderby(loan_demand.disbursement_date)
		.orderby(loan_demand.repayment_schedule_detail)
		.orderby(loan_demand.demand_type)
		.orderby(loan_demand.demand_subtype)
	)

	if loan_product:
		query = query.where(loan_demand.loan_product == loan_product)

	if demand_type:
		query = query.where(loan_demand.demand_type == demand_type)

	if demand_subtype:
		query = query.where(loan_demand.demand_subtype == demand_subtype)

	if limit:
		query = query.limit(limit)

	loan_demands = query.run(as_dict=1)

	return loan_demands


def get_pending_principal_amount(loan):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if loan.status in ("Disbursed", "Closed", "Active", "Written Off"):
		pending_principal_amount = flt(
			flt(loan.total_payment)
			+ flt(loan.debit_adjustment_amount)
			- flt(loan.credit_adjustment_amount)
			- flt(loan.total_principal_paid)
			- flt(loan.total_interest_payable)
			- flt(loan.written_off_amount)
			+ flt(loan.refund_amount),
			precision,
		)
	else:
		pending_principal_amount = flt(
			flt(loan.disbursed_amount)
			+ flt(loan.debit_adjustment_amount)
			- flt(loan.credit_adjustment_amount)
			- flt(loan.total_principal_paid)
			- flt(loan.written_off_amount)
			+ flt(loan.refund_amount),
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
	elif payment_type == "Charges Waiver":
		demand_type = "Charges"

	return demand_type, demand_subtype


def get_amounts(amounts, against_loan, posting_date, with_loan_details=False, payment_type=None):
	from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
		calculate_accrual_amount_for_loans,
		calculate_penal_interest_for_loans,
	)

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	demand_type, demand_subtype = get_demand_type(payment_type)

	against_loan_doc = frappe.get_doc("Loan", against_loan)
	unpaid_demands = get_unpaid_demands(
		against_loan_doc.name, posting_date, demand_type=demand_type, demand_subtype=demand_subtype
	)

	total_pending_interest = 0
	charges = 0
	penalty_amount = 0
	payable_principal_amount = 0

	last_demand_date = get_last_demand_date(against_loan_doc.name, posting_date)

	for demand in unpaid_demands:
		if demand.demand_subtype == "Interest":
			total_pending_interest += demand.outstanding_amount
		elif demand.demand_subtype == "Principal":
			payable_principal_amount += demand.outstanding_amount
		elif demand.demand_subtype == "Penalty":
			penalty_amount += demand.outstanding_amount
		elif demand.demand_type == "Charges":
			charges += demand.outstanding_amount

	pending_principal_amount = get_pending_principal_amount(against_loan_doc)

	accrued_interest = get_accrued_interest(against_loan, posting_date)
	total_demand_interest = get_demanded_interest(against_loan, posting_date)
	unbooked_interest = flt(accrued_interest, precision) - flt(total_demand_interest, precision)

	if getdate(posting_date) > getdate(last_demand_date):
		amounts["unaccrued_interest"] = calculate_accrual_amount_for_loans(
			against_loan_doc, posting_date=posting_date, accrual_type="Regular", is_future_accrual=1
		)

		amounts["unbooked_penalty"] = calculate_penal_interest_for_loans(
			loan=against_loan_doc, posting_date=posting_date, is_future_accrual=1
		)

	amounts["total_charges_payable"] = charges
	amounts["pending_principal_amount"] = flt(pending_principal_amount, precision)
	amounts["payable_principal_amount"] = flt(payable_principal_amount, precision)
	amounts["interest_amount"] = flt(total_pending_interest, precision)
	amounts["penalty_amount"] = flt(penalty_amount, precision)
	amounts["payable_amount"] = flt(
		payable_principal_amount + total_pending_interest + penalty_amount + charges, precision
	)
	amounts["unbooked_interest"] = flt(unbooked_interest, precision)
	amounts["written_off_amount"] = flt(against_loan_doc.written_off_amount, precision)
	amounts["unpaid_demands"] = unpaid_demands
	amounts["due_date"] = last_demand_date

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
		"unbooked_interest": 0.0,
		"unbooked_penalty": 0.0,
		"due_date": "",
		"total_charges_payable": 0.0,
		"available_security_deposit": 0.0,
	}

	if with_loan_details:
		amounts, loan_details = get_amounts(
			amounts, against_loan, posting_date, with_loan_details, payment_type=payment_type
		)
	else:
		amounts = get_amounts(amounts, against_loan, posting_date, payment_type=payment_type)

	amounts["available_security_deposit"] = frappe.db.get_value(
		"Loan Security Deposit", {"loan": against_loan}, "sum(deposit_amount - allocated_amount)"
	)

	# update values for closure
	if payment_type == "Loan Closure":
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


def get_accrued_interest(loan, posting_date, interest_type="Normal Interest"):
	accrued_interest = frappe.db.get_value(
		"Loan Interest Accrual",
		{
			"loan": loan,
			"docstatus": 1,
			"posting_date": ("<=", posting_date),
			"interest_type": interest_type,
		},
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
