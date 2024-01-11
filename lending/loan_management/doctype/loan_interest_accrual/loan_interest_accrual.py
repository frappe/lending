# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_datetime, getdate, nowdate

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand


class LoanInterestAccrual(AccountsController):
	def validate(self):
		if not self.posting_date:
			self.posting_date = nowdate()

		if not self.interest_amount and not self.payable_principal_amount:
			frappe.throw(_("Interest Amount or Principal Amount is mandatory"))

		if not self.last_accrual_date:
			self.last_accrual_date = get_last_accrual_date(self.loan, self.posting_date, self.interest_type)

	def on_submit(self):
		self.make_gl_entries()

	def on_cancel(self):
		self.make_gl_entries(cancel=1)
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]

	def make_gl_entries(self, cancel=0, adv_adj=0):
		gle_map = []

		cost_center = frappe.db.get_value("Loan", self.loan, "cost_center")
		account_details = frappe.db.get_value(
			"Loan Product",
			self.loan_product,
			["interest_accrued_account", "suspense_interest_receivable", "suspense_interest_income"],
			as_dict=1,
		)

		if self.is_npa:
			receivable_account = account_details.suspense_interest_receivable
			income_account = account_details.suspense_interest_income
		else:
			receivable_account = account_details.interest_accrued_account
			income_account = self.interest_income_account

		if self.interest_amount:
			gle_map.append(
				self.get_gl_dict(
					{
						"account": receivable_account,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"against": income_account,
						"debit": self.interest_amount,
						"debit_in_account_currency": self.interest_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.loan,
						"remarks": _("Interest accrued from {0} to {1} against loan: {2}").format(
							self.last_accrual_date, self.posting_date, self.loan
						),
						"cost_center": cost_center,
						"posting_date": self.posting_date,
					}
				)
			)

			gle_map.append(
				self.get_gl_dict(
					{
						"account": income_account,
						"against": receivable_account,
						"credit": self.interest_amount,
						"credit_in_account_currency": self.interest_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.loan,
						"remarks": ("Interest accrued from {0} to {1} against loan: {2}").format(
							self.last_accrual_date, self.posting_date, self.loan
						),
						"cost_center": cost_center,
						"posting_date": self.posting_date,
					}
				)
			)

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj)


# For Eg: If Loan disbursement date is '01-09-2019' and disbursed amount is 1000000 and
# rate of interest is 13.5 then first loan interest accrual will be on '01-10-2019'
# which means interest will be accrued for 30 days which should be equal to 11095.89
def calculate_accrual_amount_for_loans(loan, posting_date, process_loan_interest, accrual_type):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		get_pending_principal_amount,
	)

	last_accrual_date = get_last_accrual_date(loan.name, posting_date, "Normal Interest")

	if loan.is_term_loan:
		overlapping_dates = get_overlapping_dates(loan.name, last_accrual_date, posting_date)
		for date in overlapping_dates:
			pending_principal_amount = get_principal_amount_for_term_loan(loan, last_accrual_date)
			payable_interest = get_interest_for_term(
				loan, pending_principal_amount, last_accrual_date, date
			)
			if payable_interest > 0:
				make_loan_interest_accrual_entry(
					loan.name,
					pending_principal_amount,
					payable_interest,
					process_loan_interest,
					last_accrual_date,
					date,
					accrual_type,
					"Normal Interest",
					loan.rate_of_interest,
				)
			last_accrual_date = add_days(date, 1)
	else:
		no_of_days = date_diff(posting_date or nowdate(), last_accrual_date)
		if no_of_days <= 0:
			return

		pending_principal_amount = get_pending_principal_amount(loan, posting_date)

		payable_interest = get_interest_amount(
			no_of_days,
			principal_amount=pending_principal_amount,
			rate_of_interest=loan.rate_of_interest,
			company=loan.company,
			posting_date=posting_date,
		)

		if payable_interest > 0:
			make_loan_interest_accrual_entry(
				loan.name,
				pending_principal_amount,
				payable_interest,
				process_loan_interest,
				last_accrual_date,
				posting_date,
				accrual_type,
				"Normal Interest",
				loan.rate_of_interest,
			)


def get_interest_for_term(loan, pending_principal_amount, from_date, to_date):
	no_of_days = date_diff(to_date, from_date)
	payable_interest = get_interest_amount(
		no_of_days,
		principal_amount=pending_principal_amount,
		rate_of_interest=loan.rate_of_interest,
		company=loan.company,
		posting_date=to_date,
	)

	return payable_interest


def make_loan_interest_accrual_entry(
	loan,
	base_amount,
	interest_amount,
	process_loan_interest,
	start_date,
	posting_date,
	accrual_type,
	interest_type,
	rate_of_interest,
	loan_demand=None,
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	loan_interest_accrual = frappe.new_doc("Loan Interest Accrual")
	loan_interest_accrual.loan = loan
	loan_interest_accrual.interest_amount = flt(interest_amount, precision)
	loan_interest_accrual.base_amount = flt(base_amount, precision)
	loan_interest_accrual.posting_date = posting_date or nowdate()
	loan_interest_accrual.start_date = start_date
	loan_interest_accrual.process_loan_interest_accrual = process_loan_interest
	loan_interest_accrual.accrual_type = accrual_type
	loan_interest_accrual.interest_type = interest_type
	loan_interest_accrual.rate_of_interest = rate_of_interest
	loan_interest_accrual.loan_demand = loan_demand

	loan_interest_accrual.save()
	loan_interest_accrual.submit()


def get_overlapping_dates(loan, last_accrual_date, posting_date):
	loan_repayment_schedules = frappe.db.get_all(
		"Loan Repayment Schedule", filters={"loan": loan, "status": "Active"}, pluck="name"
	)
	overlapping_dates = []

	if loan_repayment_schedules and last_accrual_date:
		for schedule in loan_repayment_schedules:
			overlapping_dates = frappe.db.get_all(
				"Repayment Schedule",
				filters={"parent": schedule, "payment_date": ("between", [last_accrual_date, posting_date])},
				pluck="payment_date",
				order_by="payment_date",
			)

	overlapping_dates.append(posting_date)

	return overlapping_dates


def get_principal_amount_for_term_loan(loan, date):
	repayment_schedule = frappe.db.get_value(
		"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}, "name"
	)

	principal_amount = frappe.db.get_value(
		"Repayment Schedule",
		{"parent": repayment_schedule, "payment_date": ("<", date)},
		"balance_loan_amount",
		order_by="payment_date DESC",
	)

	if not principal_amount:
		principal_amount = loan.disbursed_amount

	return principal_amount


def get_term_loan_payment_date(loan_repayment_schedule, date):
	payment_date = frappe.db.get_value(
		"Repayment Schedule",
		{"parent": loan_repayment_schedule, "payment_date": ("<=", date)},
		"MAX(payment_date)",
	)

	return payment_date


def calculate_penal_interest_for_loans(loan, posting_date, process_loan_interest, accrual_type):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_unpaid_demands

	demands = get_unpaid_demands(loan.name, posting_date)

	loan_product = frappe.get_value("Loan", loan.name, "loan_product")
	penal_interest_rate = frappe.get_value("Loan Product", loan_product, "penalty_interest_rate")
	grace_period_days = cint(frappe.get_value("Loan Product", loan_product, "grace_period_in_days"))
	penal_interest_amount = 0

	for demand in demands:
		if demand.demand_subtype in ("Principal", "Interest"):
			if getdate(posting_date) > add_days(demand.demand_date, grace_period_days):
				last_accrual_date = get_last_accrual_date(
					loan.name, posting_date, "Penal Interest", demand=demand.name
				)

				if not last_accrual_date:
					from_date = demand.demand_date
				else:
					from_date = add_days(last_accrual_date, 1)

				no_of_days = date_diff(posting_date, from_date)

				penal_interest_amount = demand.demand_amount * penal_interest_rate * no_of_days / 36500

				if penal_interest_amount > 0:
					make_loan_interest_accrual_entry(
						loan.name,
						demand.demand_amount,
						penal_interest_amount,
						process_loan_interest,
						from_date,
						posting_date,
						accrual_type,
						"Penal Interest",
						penal_interest_rate,
						loan_demand=demand.name,
					)

					create_loan_demand(
						loan.name,
						demand.loan_repayment_schedule,
						loan.loan_disbursement,
						posting_date,
						"Penalty",
						"Penalty",
						penal_interest_amount,
					)


def make_accrual_interest_entry_for_loans(
	posting_date,
	process_loan_interest=None,
	loan=None,
	loan_product=None,
	accrual_type="Regular",
):
	query_filters = {
		"status": ("in", ["Disbursed", "Partially Disbursed", "Active"]),
		"docstatus": 1,
	}

	if loan:
		query_filters.update({"name": loan})

	if loan_product:
		query_filters.update({"loan_product": loan_product})

	open_loans = frappe.get_all(
		"Loan",
		fields=[
			"name",
			"total_payment",
			"total_amount_paid",
			"debit_adjustment_amount",
			"credit_adjustment_amount",
			"refund_amount",
			"loan_account",
			"interest_income_account",
			"penalty_income_account",
			"loan_amount",
			"is_term_loan",
			"status",
			"disbursement_date",
			"disbursed_amount",
			"applicant_type",
			"applicant",
			"rate_of_interest",
			"total_interest_payable",
			"written_off_amount",
			"total_principal_paid",
			"repayment_start_date",
			"company",
		],
		filters=query_filters,
	)

	for loan in open_loans:
		calculate_penal_interest_for_loans(loan, posting_date, process_loan_interest, accrual_type)
		calculate_accrual_amount_for_loans(loan, posting_date, process_loan_interest, accrual_type)


def get_last_accrual_date(loan, posting_date, interest_type, demand=None):
	filters = {"loan": loan, "docstatus": 1, "interest_type": interest_type}

	if demand:
		filters["loan_demand"] = demand

	last_interest_accrual_date = frappe.db.get_value(
		"Loan Interest Accrual", filters, "MAX(posting_date)"
	)
	last_disbursement_date = get_last_disbursement_date(loan, posting_date)

	if interest_type == "Penal Interest":
		return last_interest_accrual_date

	if last_interest_accrual_date:
		# interest for last interest accrual date is already booked, so add 1 day
		if last_disbursement_date and getdate(last_disbursement_date) > getdate(
			last_interest_accrual_date
		):
			last_interest_accrual_date = last_disbursement_date

		return last_interest_accrual_date
	else:
		moratorium_end_date = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan, "docstatus": 1, "status": "Active"},
			"moratorium_end_date",
		)
		print("moratorium_end_date", moratorium_end_date)
		print("last_disbursement_date", last_disbursement_date)
		if moratorium_end_date and getdate(moratorium_end_date) > getdate(last_disbursement_date):
			last_interest_accrual_date = add_days(moratorium_end_date, 1)
		else:
			last_interest_accrual_date = last_disbursement_date

		return last_interest_accrual_date


def get_last_disbursement_date(loan, posting_date):
	last_disbursement_date = frappe.db.get_value(
		"Loan Disbursement",
		{"docstatus": 1, "against_loan": loan, "posting_date": ("<", posting_date)},
		"MAX(posting_date)",
	)

	return last_disbursement_date


def days_in_year(year):
	days = 365

	if (year % 4 == 0) and (year % 100 != 0) or (year % 400 == 0):
		days = 366

	return days


def get_per_day_interest(
	principal_amount, rate_of_interest, company, posting_date=None, interest_day_count_convention=None
):
	if not posting_date:
		posting_date = getdate()

	if not interest_day_count_convention:
		interest_day_count_convention = frappe.get_cached_value(
			"Company", company, "interest_day_count_convention"
		)

	if interest_day_count_convention == "Actual/365" or interest_day_count_convention == "30/365":
		year_divisor = 365
	elif interest_day_count_convention == "30/360" or interest_day_count_convention == "Actual/360":
		year_divisor = 360
	else:
		# Default is Actual/Actual
		year_divisor = days_in_year(get_datetime(posting_date).year)

	return flt((principal_amount * rate_of_interest) / (year_divisor * 100))


def get_interest_amount(
	no_of_days,
	principal_amount=None,
	rate_of_interest=None,
	company=None,
	posting_date=None,
	interest_per_day=None,
):
	interest_day_count_convention = frappe.get_cached_value(
		"Company", company, "interest_day_count_convention"
	)

	if not interest_per_day:
		interest_per_day = get_per_day_interest(
			principal_amount, rate_of_interest, company, posting_date, interest_day_count_convention
		)

	if interest_day_count_convention == "30/365" or interest_day_count_convention == "30/360":
		no_of_days = 30

	return interest_per_day * no_of_days
