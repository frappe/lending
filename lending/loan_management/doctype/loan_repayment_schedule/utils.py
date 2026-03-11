import math

import frappe
from frappe.utils import add_months, cint, flt, get_last_day, getdate


def add_single_month(date):
	if getdate(date) == get_last_day(date):
		return get_last_day(add_months(date, 1))
	else:
		return add_months(date, 1)


def get_monthly_repayment_amount(loan_amount, rate_of_interest, repayment_periods, frequency):
	if frequency == "One Time":
		repayment_periods = 1

	if rate_of_interest:
		monthly_interest_rate = flt(rate_of_interest) / (get_frequency(frequency) * 100)
		monthly_repayment_amount = math.ceil(
			(loan_amount * monthly_interest_rate * (1 + monthly_interest_rate) ** repayment_periods)
			/ ((1 + monthly_interest_rate) ** repayment_periods - 1)
		)
	else:
		monthly_repayment_amount = math.ceil(flt(loan_amount) / repayment_periods)
	return monthly_repayment_amount

def get_repayment_periods(loan_amount, rate_of_interest, monthly_repayment_amount, frequency):
	if frequency == "One Time":
		return 1

	monthly_interest_rate = flt(rate_of_interest) / (get_frequency(frequency) * 100)
	repayment_periods = math.log(
		flt(monthly_repayment_amount) / (flt(monthly_repayment_amount) - (loan_amount * monthly_interest_rate)),
		1 + monthly_interest_rate,
	)

	return math.ceil(repayment_periods)

def get_flat_monthly_repayment_amount(loan_amount, rate_of_interest, repayment_periods, frequency):
	if frequency == "Monthly":
		years = 12
	else:
		years = 1

	total_interest = loan_amount * rate_of_interest * repayment_periods/ (years * 100)
	total_amount = loan_amount + total_interest
	monthly_repayment_amount = math.ceil(flt(total_amount) / repayment_periods)

	return monthly_repayment_amount


def get_frequency(frequency):
	return {
		"Monthly": 12,
		"Bi-Weekly": 26,
		"Weekly": 52,
		"Daily": 365,
		"Quarterly": 4,
		"One Time": 1,
	}.get(frequency)


def set_demand(row_name):
	frappe.db.set_value("Repayment Schedule", row_name, "demand_generated", 1)


def get_amounts(
	balance_amount,
	rate_of_interest,
	days,
	months,
	monthly_repayment_amount,
	carry_forward_interest=0,
	previous_interest_amount=0,
	additional_principal_amount=0,
	pending_prev_days=0,
	flat_rate=False,
	loan_amount=0,
	bpi_amount=0,
	disbursement_charges=0
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if additional_principal_amount:
		current_balance_amount = additional_principal_amount
		additional_principal_amount = 0
	else:
		current_balance_amount = balance_amount

	if flat_rate:
		interest_amount = flt((loan_amount * flt(rate_of_interest)) / (months * 100), precision)
	else:
		interest_amount = flt(
			current_balance_amount * flt(rate_of_interest) * days / (months * 100), precision
		)

	if bpi_amount:
		interest_amount += bpi_amount

	principal_amount = monthly_repayment_amount - flt(interest_amount) - flt(disbursement_charges)

	if carry_forward_interest:
		interest_amount += carry_forward_interest

	if previous_interest_amount > 0:
		interest_amount += previous_interest_amount
		principal_amount -= previous_interest_amount
		previous_interest_amount = 0

	if interest_amount > monthly_repayment_amount:
		previous_interest_amount = interest_amount - monthly_repayment_amount
		interest_amount = monthly_repayment_amount
		principal_amount = 0

	balance_amount = flt(balance_amount + interest_amount - monthly_repayment_amount, 2)

	if balance_amount < 0:
		principal_amount += balance_amount
		balance_amount = 0.0

	total_payment = principal_amount + interest_amount

	if pending_prev_days > 0:
		days += pending_prev_days
		pending_prev_days = 0

	return (
		interest_amount,
		principal_amount,
		disbursement_charges,
		balance_amount,
		total_payment,
		days,
		previous_interest_amount,
	)


def get_loan_partner_details(loan_partner):
	loan_partner_details = frappe.db.get_value(
		"Loan Partner",
		loan_partner,
		[
			"partner_loan_share_percentage",
			"repayment_schedule_type",
			"receivable_account",
			"credit_account",
			"enable_partner_accounting",
		],
		as_dict=True,
	)

	return loan_partner_details
