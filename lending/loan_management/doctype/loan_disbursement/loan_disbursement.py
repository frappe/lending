# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import add_days, flt, get_datetime, nowdate

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_security_unpledge.loan_security_unpledge import (
	get_pledged_security_qty,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_demand_loans,
)


class LoanDisbursement(AccountsController):
	def validate(self):
		self.set_missing_values()
		self.validate_disbursal_amount()

	def on_submit(self):
		if self.is_term_loan:
			self.update_repayment_schedule_status()

		self.set_status_and_amounts()
		self.withheld_security_deposit()
		self.make_gl_entries()

	def update_repayment_schedule_status(self, cancel=0):
		if cancel:
			status = "Initiated"
			current_status = "Active"
		else:
			status = "Active"
			current_status = "Initiated"

		schedule = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": self.against_loan, "docstatus": 1, "status": current_status},
			"name",
		)

		frappe.db.set_value("Loan Repayment Schedule", schedule, "status", status)

	def on_cancel(self):
		if self.is_term_loan:
			self.update_repayment_schedule_status(cancel=1)

		self.delete_security_deposit()
		self.set_status_and_amounts(cancel=1)
		self.make_gl_entries(cancel=1)
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]

	def set_missing_values(self):
		if not self.disbursement_date:
			self.disbursement_date = nowdate()

		if not self.cost_center:
			self.cost_center = erpnext.get_default_cost_center(self.company)

		if not self.posting_date:
			self.posting_date = self.disbursement_date or nowdate()

	def withheld_security_deposit(self):
		if self.withhold_security_deposit:
			sd = frappe.get_doc(
				{
					"doctype": "Loan Security Deposit",
					"loan": self.against_loan,
					"loan_disbursement": self.name,
					"deposit_amount": self.monthly_repayment_amount,
				}
			).insert()
			sd.submit()

	def delete_security_deposit(self):
		if self.withhold_security_deposit:
			sd = frappe.get_doc("Loan Security Deposit", {"loan_disbursement": self.name})
			sd.cancel()
			sd.delete()

	def validate_disbursal_amount(self):
		possible_disbursal_amount = get_disbursal_amount(self.against_loan)

		if not self.disbursed_amount:
			frappe.throw(_("Disbursed amount cannot be zero"))

		elif self.disbursed_amount > possible_disbursal_amount:
			frappe.throw(_("Disbursed Amount cannot be greater than {0}").format(possible_disbursal_amount))

	def set_status_and_amounts(self, cancel=0):
		loan_details = frappe.get_all(
			"Loan",
			fields=[
				"loan_amount",
				"disbursed_amount",
				"total_payment",
				"total_principal_paid",
				"total_interest_payable",
				"status",
				"is_term_loan",
				"is_secured_loan",
			],
			filters={"name": self.against_loan},
		)[0]

		if cancel:
			disbursed_amount, status, total_payment = self.get_values_on_cancel(loan_details)
		else:
			disbursed_amount, status, total_payment = self.get_values_on_submit(loan_details)

		frappe.db.set_value(
			"Loan",
			self.against_loan,
			{
				"disbursement_date": self.disbursement_date,
				"disbursed_amount": disbursed_amount,
				"status": status,
				"total_payment": total_payment,
			},
		)

	def get_values_on_cancel(self, loan_details):
		disbursed_amount = loan_details.disbursed_amount - self.disbursed_amount
		total_payment = loan_details.total_payment

		if loan_details.disbursed_amount > loan_details.loan_amount:
			topup_amount = loan_details.disbursed_amount - loan_details.loan_amount
			if topup_amount > self.disbursed_amount:
				topup_amount = self.disbursed_amount

			total_payment = total_payment - topup_amount

		if disbursed_amount == 0:
			status = "Sanctioned"

		elif disbursed_amount >= loan_details.loan_amount:
			status = "Disbursed"
		else:
			status = "Partially Disbursed"

		return disbursed_amount, status, total_payment

	def get_values_on_submit(self, loan_details):
		disbursed_amount = self.disbursed_amount + loan_details.disbursed_amount
		total_payment = loan_details.total_payment

		if loan_details.status in ("Disbursed", "Partially Disbursed") and not loan_details.is_term_loan:
			process_loan_interest_accrual_for_demand_loans(
				posting_date=add_days(self.disbursement_date, -1),
				loan=self.against_loan,
				accrual_type="Disbursement",
			)

		if disbursed_amount > loan_details.loan_amount:
			topup_amount = disbursed_amount - loan_details.loan_amount

			if topup_amount < 0:
				topup_amount = 0

			if topup_amount > self.disbursed_amount:
				topup_amount = self.disbursed_amount

			total_payment = total_payment + topup_amount

		if flt(disbursed_amount) >= loan_details.loan_amount:
			status = "Disbursed"
		else:
			status = "Partially Disbursed"

		return disbursed_amount, status, total_payment

	def make_gl_entries(self, cancel=0, adv_adj=0):
		gle_map = []

		gle_map.append(
			self.get_gl_dict(
				{
					"account": self.loan_account,
					"against": self.disbursement_account,
					"debit": self.disbursed_amount,
					"debit_in_account_currency": self.disbursed_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.against_loan,
					"remarks": _("Disbursement against loan:") + self.against_loan,
					"cost_center": self.cost_center,
					"party_type": self.applicant_type,
					"party": self.applicant,
					"posting_date": self.disbursement_date,
				}
			)
		)

		gle_map.append(
			self.get_gl_dict(
				{
					"account": self.disbursement_account,
					"against": self.loan_account,
					"credit": self.disbursed_amount,
					"credit_in_account_currency": self.disbursed_amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.against_loan,
					"remarks": _("Disbursement against loan:") + self.against_loan,
					"cost_center": self.cost_center,
					"posting_date": self.disbursement_date,
				}
			)
		)

		if self.withhold_security_deposit:
			security_deposit_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "security_deposit_account"
			)
			gle_map.append(
				self.get_gl_dict(
					{
						"account": security_deposit_account,
						"against": self.disbursement_account,
						"credit": self.monthly_repayment_amount,
						"credit_in_account_currency": self.monthly_repayment_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.against_loan,
						"remarks": _("Disbursement against loan:") + self.against_loan,
						"cost_center": self.cost_center,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"posting_date": self.disbursement_date,
					}
				)
			)

			gle_map.append(
				self.get_gl_dict(
					{
						"account": self.disbursement_account,
						"against": self.loan_account,
						"credit": -1 * self.monthly_repayment_amount,
						"credit_in_account_currency": -1 * self.monthly_repayment_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.against_loan,
						"remarks": _("Disbursement against loan:") + self.against_loan,
						"cost_center": self.cost_center,
						"posting_date": self.disbursement_date,
					}
				)
			)

		for charge in self.get("loan_disbursement_charges"):
			gle_map.append(
				self.get_gl_dict(
					{
						"account": charge.account,
						"against": self.disbursement_account,
						"credit": charge.amount,
						"credit_in_account_currency": charge.amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.against_loan,
						"remarks": _("Disbursement against loan:") + self.against_loan,
						"cost_center": self.cost_center,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"posting_date": self.disbursement_date,
					}
				)
			)

			gle_map.append(
				self.get_gl_dict(
					{
						"account": self.disbursement_account,
						"against": self.loan_account,
						"credit": -1 * charge.amount,
						"credit_in_account_currency": -1 * charge.amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.against_loan,
						"remarks": _("Disbursement against loan:") + self.against_loan,
						"cost_center": self.cost_center,
						"posting_date": self.disbursement_date,
					}
				)
			)

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj)


def get_total_pledged_security_value(loan):
	update_time = get_datetime()

	loan_security_price_map = frappe._dict(
		frappe.get_all(
			"Loan Security Price",
			fields=["loan_security", "loan_security_price"],
			filters={"valid_from": ("<=", update_time), "valid_upto": (">=", update_time)},
			as_list=1,
		)
	)

	hair_cut_map = frappe._dict(
		frappe.get_all("Loan Security", fields=["name", "haircut"], as_list=1)
	)

	security_value = 0.0
	pledged_securities = get_pledged_security_qty(loan)

	for security, qty in pledged_securities.items():
		after_haircut_percentage = 100 - hair_cut_map.get(security)
		security_value += (
			loan_security_price_map.get(security, 0) * qty * after_haircut_percentage
		) / 100

	return security_value


@frappe.whitelist()
def get_disbursal_amount(loan, on_current_security_price=0):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		get_pending_principal_amount,
	)

	loan_details = frappe.get_value(
		"Loan",
		loan,
		[
			"loan_amount",
			"disbursed_amount",
			"total_payment",
			"debit_adjustment_amount",
			"credit_adjustment_amount",
			"refund_amount",
			"total_principal_paid",
			"total_interest_payable",
			"status",
			"is_term_loan",
			"is_secured_loan",
			"maximum_loan_amount",
			"written_off_amount",
		],
		as_dict=1,
	)

	if loan_details.is_secured_loan and frappe.get_all(
		"Loan Security Shortfall", filters={"loan": loan, "status": "Pending"}
	):
		return 0

	pending_principal_amount = get_pending_principal_amount(loan_details)

	security_value = 0.0
	if loan_details.is_secured_loan and on_current_security_price:
		security_value = get_total_pledged_security_value(loan)

	if loan_details.is_secured_loan and not on_current_security_price:
		security_value = get_maximum_amount_as_per_pledged_security(loan)

	if not security_value and not loan_details.is_secured_loan:
		security_value = flt(loan_details.loan_amount)

	disbursal_amount = flt(security_value) - flt(pending_principal_amount)

	if (
		loan_details.is_term_loan
		and (disbursal_amount + loan_details.loan_amount) > loan_details.loan_amount
	):
		disbursal_amount = loan_details.loan_amount - loan_details.disbursed_amount

	return disbursal_amount


def get_maximum_amount_as_per_pledged_security(loan):
	return flt(frappe.db.get_value("Loan Security Pledge", {"loan": loan}, "sum(maximum_loan_value)"))
