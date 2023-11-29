# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import (
	add_days,
	add_months,
	cint,
	date_diff,
	flt,
	get_datetime,
	get_last_day,
	getdate,
	nowdate,
)

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan.loan import get_cyclic_date
from lending.loan_management.doctype.loan_security_assignment.loan_security_assignment import (
	update_loan_securities_values,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)


class LoanDisbursement(AccountsController):
	def validate(self):
		self.set_missing_values()
		self.validate_disbursal_amount()
		if self.repayment_schedule_type == "Line of Credit":
			self.set_cyclic_date()

		if self.is_term_loan and not self.is_new():
			self.update_draft_schedule()

	def after_insert(self):
		self.make_draft_schedule()

	def on_trash(self):
		if self.docstatus == 0:
			draft_schedule = self.get_draft_schedule()
			frappe.delete_doc("Loan Repayment Schedule", draft_schedule)

	def get_schedule_details(self):
		disbursed_amount = self.get_disbursed_amount()

		return {
			"doctype": "Loan Repayment Schedule",
			"loan": self.against_loan,
			"repayment_method": self.repayment_method,
			"repayment_start_date": self.repayment_start_date,
			"repayment_periods": self.tenure,
			"posting_date": self.disbursement_date,
			"repayment_frequency": self.repayment_frequency,
			"disbursed_amount": disbursed_amount,
			"loan_disbursement": self.name,
		}

	def make_draft_schedule(self):
		loan_product = frappe.db.get_value("Loan", self.against_loan, "loan_product")
		loan_details = frappe.db.get_value(
			"Loan", self.against_loan, ["repayment_periods", "moratorium_tenure", "status"], as_dict=1
		)
		if self.repayment_schedule_type != "Line of Credit":
			if not self.repayment_start_date:
				self.repayment_start_date = get_cyclic_date(loan_product, self.posting_date)

				if loan_details.status == "Sanctioned" and loan_details.moratorium_tenure:
					self.repayment_start_date = add_months(
						self.repayment_start_date, loan_details.moratorium_tenure
					)
		already_accrued_months = self.get_already_accrued_months()
		self.tenure = loan_details.repayment_periods - already_accrued_months

		schedule = frappe.get_doc(self.get_schedule_details()).insert()
		self.monthly_repayment_amount = schedule.monthly_repayment_amount
		self.broken_period_interest = schedule.broken_period_interest

	def get_already_accrued_months(self):
		already_accrued_months = 0
		existing_schedule = frappe.db.get_all(
			"Loan Repayment Schedule",
			{"loan": self.against_loan, "docstatus": 1, "status": ("in", ["Active", "Outdated"])},
			pluck="name",
		)

		if existing_schedule:
			already_accrued_months = frappe.db.count(
				"Repayment Schedule", {"parent": ("in", existing_schedule), "is_accrued": 1}
			)

		return already_accrued_months

	def get_disbursed_amount(self):
		if self.repayment_schedule_type == "Line of Credit":
			disbursed_amount = self.disbursed_amount
		else:
			current_disbursed_amount = frappe.db.get_value("Loan", self.against_loan, "disbursed_amount")
			disbursed_amount = self.disbursed_amount + current_disbursed_amount

		return disbursed_amount

	def get_draft_schedule(self):
		return frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": self.against_loan, "docstatus": 0}, "name"
		)

	def update_draft_schedule(self):
		draft_schedule = self.get_draft_schedule()

		if self.repayment_frequency == "Monthly" and not self.repayment_start_date:
			loan_details = frappe.db.get_value(
				"Loan", self.against_loan, ["status", "moratorium_tenure", "loan_product"], as_dict=1
			)

			self.repayment_start_date = get_cyclic_date(loan_details.loan_product, self.posting_date)
			if loan_details.status == "Sanctioned" and loan_details.moratorium_tenure:
				self.repayment_start_date = add_months(
					self.repayment_start_date, loan_details.moratorium_tenure
				)

		if draft_schedule:
			schedule = frappe.get_doc("Loan Repayment Schedule", draft_schedule)
			schedule.update(self.get_schedule_details())
			schedule.save()

			self.broken_period_interest = schedule.broken_period_interest
			self.monthly_repayment_amount = schedule.monthly_repayment_amount

	def on_submit(self):
		if self.is_term_loan:
			self.update_current_repayment_schedule()
			self.submit_repayment_schedule()
			self.update_repayment_schedule_status()

		self.set_status_and_amounts()

		update_loan_securities_values(self.against_loan, self.disbursed_amount, self.doctype)
		self.set_status_of_loan_securities()

		self.withheld_security_deposit()
		self.make_gl_entries()

	def submit_repayment_schedule(self):
		filters = {
			"loan": self.against_loan,
			"docstatus": 0,
			"status": "Initiated",
			"loan_disbursement": self.name,
		}
		schedule = frappe.get_doc("Loan Repayment Schedule", filters)
		schedule.submit()

	def cancel_and_delete_repayment_schedule(self):
		if self.repayment_schedule_type == "Line of Credit":
			filters = {
				"loan": self.against_loan,
				"docstatus": 1,
				"status": "Active",
				"loan_disbursement": self.name,
			}
			schedule = frappe.get_doc("Loan Repayment Schedule", filters)
			schedule.cancel()

	def update_current_repayment_schedule(self, cancel=0):
		# Update status of existing schedule on topup
		if cancel:
			status = "Active"
			current_status = "Outdated"
		else:
			status = "Outdated"
			current_status = "Active"

		if self.repayment_schedule_type != "Line of Credit":
			existing_schedule = frappe.db.get_value(
				"Loan Repayment Schedule",
				{"loan": self.against_loan, "docstatus": 1, "status": current_status},
			)

			if existing_schedule:
				frappe.db.set_value("Loan Repayment Schedule", existing_schedule, "status", status)

	def update_repayment_schedule_status(self, cancel=0):
		if cancel:
			status = "Initiated"
			current_status = "Active"
		else:
			status = "Active"
			current_status = "Initiated"

		filters = {"loan": self.against_loan, "docstatus": 1, "status": current_status}
		schedule = frappe.db.get_value(
			"Loan Repayment Schedule",
			filters,
			"name",
		)
		frappe.db.set_value("Loan Repayment Schedule", schedule, "status", status)

	def on_cancel(self):
		if self.is_term_loan:
			self.cancel_and_delete_repayment_schedule()
			self.update_repayment_schedule_status(cancel=1)
			self.update_current_repayment_schedule(cancel=1)

		self.delete_security_deposit()
		self.set_status_and_amounts(cancel=1)

		update_loan_securities_values(
			self.against_loan,
			self.disbursed_amount,
			self.doctype,
			on_trigger_doc_cancel=1,
		)
		self.set_status_of_loan_securities(cancel=1)

		self.make_gl_entries(cancel=1)
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]

	def set_missing_values(self):
		if not self.disbursement_date:
			self.disbursement_date = nowdate()

		if not self.cost_center:
			self.cost_center = erpnext.get_default_cost_center(self.company)

		if not self.posting_date:
			self.posting_date = self.disbursement_date or nowdate()

		if not self.disbursement_account and self.bank_account:
			self.disbursement_account = frappe.db.get_value("Bank Account", self.bank_account, "account")

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

	def set_cyclic_date(self):
		if self.repayment_frequency == "Monthly" and not self.repayment_start_date:
			cycle_day, min_days_bw_disbursement_first_repayment = frappe.db.get_value(
				"Loan Product",
				self.loan_product,
				["cyclic_day_of_the_month", "min_days_bw_disbursement_first_repayment"],
			)
			cycle_day = cint(cycle_day)

			last_day_of_month = get_last_day(self.posting_date)
			cyclic_date = add_days(last_day_of_month, cycle_day)

			broken_period_days = date_diff(cyclic_date, self.posting_date)
			if broken_period_days < min_days_bw_disbursement_first_repayment:
				cyclic_date = add_days(get_last_day(cyclic_date), cycle_day)

			self.repayment_start_date = cyclic_date

	def delete_security_deposit(self):
		if self.withhold_security_deposit:
			sd = frappe.get_doc("Loan Security Deposit", {"loan_disbursement": self.name})
			sd.cancel()
			sd.delete()

	def validate_disbursal_amount(self):
		possible_disbursal_amount, pending_principal_amount = get_disbursal_amount(self.against_loan)
		limit_details = frappe.db.get_value(
			"Loan",
			self.against_loan,
			[
				"limit_applicable_start",
				"limit_applicable_end",
				"available_limit_amount",
			],
			as_dict=1,
		)

		if not self.disbursed_amount:
			frappe.throw(_("Disbursed amount cannot be zero"))
		elif self.disbursed_amount > possible_disbursal_amount:
			frappe.throw(_("Disbursed Amount cannot be greater than {0}").format(possible_disbursal_amount))
		elif self.repayment_schedule_type == "Line of Credit":
			if (
				getdate(limit_details.limit_applicable_end)
				< getdate(self.disbursement_date)
				< getdate(limit_details.limit_applicable_start)
			):
				frappe.throw("Disbursement date is out of approved limit dates")

		elif self.disbursed_amount > possible_disbursal_amount:
			frappe.throw(_("Disbursed Amount cannot be greater than {0}").format(possible_disbursal_amount))

		if limit_details.available_limit_amount and self.disbursed_amount > flt(
			limit_details.available_limit_amount
		):
			frappe.throw(_("Disbursement amount cannot be greater than available limit amount"))

	def set_status_of_loan_securities(self, cancel=0):
		if not frappe.db.get_value("Loan", self.against_loan, "is_secured_loan"):
			return

		if not cancel:
			new_status = "Hypothecated"
			old_status = "Pending Hypothecation"
		else:
			new_status = "Pending Hypothecation"
			old_status = "Hypothecated"

		frappe.db.sql(
			"""
			UPDATE `tabLoan Security` ls
			JOIN `tabPledge` p ON p.loan_security=ls.name
			JOIN `tabLoan Security Assignment` lsa ON lsa.name=p.parent
			JOIN `tabLoan Security Assignment Loan Detail` lsald ON lsald.parent=lsa.name
			SET ls.status=%s
			WHERE lsald.loan=%s AND ls.status=%s
		""",
			(new_status, self.against_loan, old_status),
		)

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
				"maximum_limit_amount",
				"available_limit_amount",
				"utilized_limit_amount",
			],
			filters={"name": self.against_loan},
		)[0]

		if cancel:
			(
				disbursed_amount,
				status,
				total_payment,
				new_available_limit_amount,
				new_utilized_limit_amount,
			) = self.get_values_on_cancel(loan_details)
		else:
			(
				disbursed_amount,
				status,
				total_payment,
				new_available_limit_amount,
				new_utilized_limit_amount,
			) = self.get_values_on_submit(loan_details)

		frappe.db.set_value(
			"Loan",
			self.against_loan,
			{
				"disbursement_date": self.disbursement_date,
				"disbursed_amount": disbursed_amount,
				"status": status,
				"total_payment": total_payment,
				"available_limit_amount": new_available_limit_amount,
				"utilized_limit_amount": new_utilized_limit_amount,
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

		if disbursed_amount <= 0:
			status = "Sanctioned"
		elif disbursed_amount >= loan_details.loan_amount:
			status = "Disbursed"
		else:
			status = "Partially Disbursed"

		new_available_limit_amount = (
			loan_details.available_limit_amount + self.disbursed_amount
			if loan_details.available_limit_amount
			else 0.0
		)
		new_utilized_limit_amount = (
			loan_details.utilized_limit_amount - self.disbursed_amount
			if loan_details.utilized_limit_amount
			else 0.0
		)

		return (
			disbursed_amount,
			status,
			total_payment,
			new_available_limit_amount,
			new_utilized_limit_amount,
		)

	def get_values_on_submit(self, loan_details):
		disbursed_amount = self.disbursed_amount + loan_details.disbursed_amount

		total_payment = loan_details.total_payment

		if loan_details.status in ("Disbursed", "Partially Disbursed") and not loan_details.is_term_loan:
			process_loan_interest_accrual_for_loans(
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

		if self.repayment_schedule_type == "Line of Credit":
			status = "Active"
		elif flt(disbursed_amount) >= loan_details.loan_amount:
			status = "Disbursed"
		else:
			status = "Partially Disbursed"

		new_available_limit_amount = (
			loan_details.available_limit_amount - self.disbursed_amount
			if loan_details.maximum_limit_amount
			else 0.0
		)
		new_utilized_limit_amount = (
			loan_details.utilized_limit_amount + self.disbursed_amount
			if loan_details.maximum_limit_amount
			else 0.0
		)

		return (
			disbursed_amount,
			status,
			total_payment,
			new_available_limit_amount,
			new_utilized_limit_amount,
		)

	def add_gl_entry(self, gl_entries, account, against_account, amount, remarks=None):
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": account,
					"against": against_account,
					"debit": amount,
					"debit_in_account_currency": amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.against_loan,
					"remarks": remarks,
					"cost_center": self.cost_center,
					"party_type": self.applicant_type,
					"party": self.applicant,
					"posting_date": self.disbursement_date,
				}
			)
		)

		gl_entries.append(
			self.get_gl_dict(
				{
					"account": against_account,
					"against": account,
					"debit": -1 * amount,
					"debit_in_account_currency": amount,
					"against_voucher_type": "Loan",
					"against_voucher": self.against_loan,
					"remarks": remarks,
					"cost_center": self.cost_center,
					"posting_date": self.disbursement_date,
				}
			)
		)

	def make_gl_entries(self, cancel=0, adv_adj=0):
		gle_map = []
		remarks = _("Disbursement against loan:") + self.against_loan

		self.add_gl_entry(
			gle_map, self.loan_account, self.disbursement_account, self.disbursed_amount, remarks
		)

		if self.withhold_security_deposit:
			security_deposit_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "security_deposit_account"
			)

			self.add_gl_entry(
				gle_map,
				security_deposit_account,
				self.disbursement_account,
				-1 * self.monthly_repayment_amount,
				remarks,
			)

		if self.broken_period_interest:
			broken_period_interest_account = frappe.db.get_value(
				"Loan Product", self.loan_product, "broken_period_interest_recovery_account"
			)
			self.add_gl_entry(
				gle_map,
				broken_period_interest_account,
				self.disbursement_account,
				-1 * self.broken_period_interest,
				remarks,
			)

		for charge in self.get("loan_disbursement_charges"):
			self.add_gl_entry(gle_map, charge.account, self.disbursement_account, charge.amount, remarks)

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

	return disbursal_amount, pending_principal_amount


def get_maximum_amount_as_per_pledged_security(loan):
	lsa = frappe.qb.DocType("Loan Security Assignment")
	lsald = frappe.qb.DocType("Loan Security Assignment Loan Detail")

	maximum_loan_value = (
		frappe.qb.from_(lsa)
		.inner_join(lsald)
		.on(lsald.parent == lsa.name)
		.select(Sum(lsa.maximum_loan_value))
		.where(lsa.status == "Pledged")
		.where(lsald.loan == loan)
	).run()

	return maximum_loan_value[0][0] if maximum_loan_value else 0
