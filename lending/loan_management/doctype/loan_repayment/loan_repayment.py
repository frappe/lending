# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, get_datetime, getdate

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan.loan import update_all_linked_loan_customer_npa_status

# from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
# 	get_last_accrual_date,
# 	get_per_day_interest,
# )
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	update_shortfall_status,
)

# from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
# 	create_process_loan_classification,
# )


class LoanRepayment(AccountsController):
	def validate(self):
		amounts = calculate_amounts(self.against_loan, self.posting_date)
		self.set_missing_values(amounts)
		self.check_future_entries()
		self.validate_amount()
		self.allocate_amount_against_demands(amounts)

	def on_submit(self):
		# if self.repayment_type == "Normal Repayment":
		# 	create_process_loan_classification(
		# 		posting_date=self.posting_date,
		# 		loan_product=self.loan_product,
		# 		loan=self.against_loan,
		# 		payment_reference=self.name,
		# 	)

		self.update_paid_amounts()
		self.update_demands()
		self.update_limits()
		update_installment_counts(self.against_loan)

		if self.repayment_type == "Charges Waiver":
			self.make_credit_note()

		self.make_gl_entries()

	def on_cancel(self):
		self.check_future_accruals()

		if self.repayment_type == "Normal Repayment":
			self.mark_as_unpaid()
			self.update_demands(cancel=1)
			self.update_limits(cancel=1)
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
		update_installment_counts(self.against_loan)

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

	def update_paid_amounts(self):
		if self.repayment_type == "Normal Repayment":
			loan = frappe.qb.DocType("Loan")
			query = (
				frappe.qb.update(loan)
				.set(loan.total_amount_paid, loan.total_amount_paid + self.amount_paid)
				.set(loan.total_principal_paid, loan.total_principal_paid + self.principal_amount_paid)
				.where(loan.name == self.against_loan)
			)

			pending_principal_amount = get_pending_principal_amount(loan)
			if not loan.is_secured_loan and pending_principal_amount <= 0:
				query = query.set(loan.status, "Loan Closure Requested")
			query.run()

			update_shortfall_status(self.against_loan, self.principal_amount_paid)

	def mark_as_unpaid(self):
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
			frappe.qb.update(loan_demand).set(
				loan_demand.paid_amount, loan_demand.paid_amount + paid_amount
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

	def allocate_amount_against_demands(self, amounts):
		# precision = cint(frappe.db.get_default("currency_precision")) or 2
		self.set("repayment_details", [])
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

		# interest_paid -= self.principal_amount_paid
		amount_paid = self.apply_allocation_order(
			allocation_order, amount_paid, amounts.get("unpaid_demands")
		)

		for payment in self.repayment_details:
			if payment.demand_type == "Interest":
				self.total_interest_paid += payment.paid_amount
			elif payment.demand_type == "Principal":
				self.principal_amount_paid += payment.paid_amount
			elif payment.demand_type == "Penalty":
				self.total_penalty_paid += payment.paid_amount
			elif payment.demand_type == "Charges":
				self.total_charges_paid += payment.paid_amount

		if amount_paid > 0:
			self.principal_amount_paid += amount_paid
			amount_paid = 0

	def apply_allocation_order(self, allocation_order, pending_amount, demands):
		"""Allocate amount based on allocation order"""
		allocation_order_doc = frappe.get_doc("Loan Demand Offset Order", allocation_order)
		for d in allocation_order_doc.get("components"):
			if d.demand_type == "EMI (Principal + Interest)" and pending_amount > 0:
				pending_amount = self.adjust_component(
					pending_amount, "EMI", ["Interest", "Principal"], demands
				)
			if d.demand_type == "Principal" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Normal", ["Principal"], demands)
			if d.demand_type == "Interest" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Normal", ["Interest"], demands)
			if d.demand_type == "Penalty" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Penalty", ["Penalty"], demands)
			if d.demand_type == "Charges" and pending_amount > 0:
				pending_amount = self.adjust_component(pending_amount, "Normal", ["Charges"], demands)

		return pending_amount

	def adjust_component(self, amount_to_adjust, demand_type, demand_subtypes, demands):
		for demand in demands:
			if demand.demand_type == demand_type and demand.demand_subtype in demand_subtypes:
				if amount_to_adjust >= demand.demand_amount:
					self.append(
						"repayment_details",
						{
							"loan_demand": demand.name,
							"paid_amount": demand.demand_amount,
							"demand_type": demand.demand_subtype,
						},
					)
					amount_to_adjust -= flt(demand.demand_amount)
				elif amount_to_adjust > 0:
					self.append(
						"repayment_details",
						{
							"loan_demand": demand.name,
							"paid_amount": amount_to_adjust,
							"demand_type": demand.demand_subtype,
						},
					)
					amount_to_adjust = 0

		return amount_to_adjust

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
				"penalty_receivable_account",
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
			if repayment.demand_type == "Interest":
				against_account = account_details.interest_receivable_account
			elif repayment.demand_type == "Principal":
				against_account = self.loan_account
			elif repayment.demand_type == "Penalty":
				against_account = account_details.penalty_receivable_account

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


def get_unpaid_demands(against_loan, posting_date=None):
	if not posting_date:
		posting_date = getdate()

	# precision = cint(frappe.db.get_default("currency_precision")) or 2

	loan_demand = frappe.qb.DocType("Loan Demand")
	loan_demands = (
		frappe.qb.from_(loan_demand)
		.select(
			loan_demand.name,
			loan_demand.loan_repayment_schedule,
			loan_demand.loan_disbursement,
			loan_demand.demand_date,
			loan_demand.last_repayment_date,
			(loan_demand.demand_amount - loan_demand.paid_amount).as_("demand_amount"),
			loan_demand.demand_subtype,
			loan_demand.demand_type,
		)
		.where(
			(loan_demand.loan == against_loan)
			& (loan_demand.docstatus == 1)
			& (loan_demand.demand_date <= posting_date)
			& (loan_demand.demand_amount - loan_demand.paid_amount > 0)
		)
		.orderby(loan_demand.disbursement_date)
		.orderby(loan_demand.repayment_schedule_detail)
		.orderby(loan_demand.demand_type)
		.orderby(loan_demand.demand_subtype)
		.run(as_dict=1)
	)

	return loan_demands


def get_pending_principal_amount(loan, posting_date=None):
	precision = cint(frappe.db.get_default("currency_precision"))

	if loan.status in ("Disbursed", "Closed"):
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
			- flt(loan.total_interest_payable)
			- flt(loan.written_off_amount)
			+ flt(loan.refund_amount),
			precision,
		)

	return pending_principal_amount


# This function returns the amounts that are payable at the time of loan repayment based on posting date
# So it pulls all the unpaid Loan Interest Accrual Entries and calculates the penalty if applicable


def get_amounts(amounts, against_loan, posting_date, with_loan_details=False):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	against_loan_doc = frappe.get_doc("Loan", against_loan)
	unpaid_demands = get_unpaid_demands(against_loan_doc.name, posting_date)
	total_pending_interest = 0
	charges = 0
	penalty_amount = 0
	payable_principal_amount = 0
	final_due_date = ""

	for demand in unpaid_demands:
		if demand.demand_subtype == "Interest":
			total_pending_interest += demand.demand_amount
		elif demand.demand_subtype == "Principal":
			payable_principal_amount += demand.demand_amount
		elif demand.demand_subtype == "Penalty":
			penalty_amount += demand.demand_amount
		elif demand.demand_type == "Charges":
			charges += demand.demand_amount

	pending_principal_amount = get_pending_principal_amount(against_loan_doc)

	unbooked_interest = 0

	amounts["charges"] = charges
	amounts["pending_principal_amount"] = flt(pending_principal_amount, precision)
	amounts["payable_principal_amount"] = flt(payable_principal_amount, precision)
	amounts["interest_amount"] = flt(total_pending_interest, precision)
	amounts["penalty_amount"] = flt(penalty_amount, precision)
	amounts["payable_amount"] = flt(
		payable_principal_amount + total_pending_interest + penalty_amount, precision
	)
	amounts["unbooked_interest"] = flt(unbooked_interest, precision)
	amounts["written_off_amount"] = flt(against_loan_doc.written_off_amount, precision)
	amounts["unpaid_demands"] = unpaid_demands

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
