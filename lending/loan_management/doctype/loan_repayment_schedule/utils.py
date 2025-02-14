import math

import frappe
from frappe.utils import add_months, cint, flt, get_last_day, getdate


def add_single_month(date):
	if getdate(date) == get_last_day(date):
		return get_last_day(add_months(date, 1))
	else:
		return add_months(date, 1)


def get_monthly_repayment_amount(
	loan_amount, rate_of_interest, repayment_periods, frequency, ceil_monthly_repayment=False
):
	if frequency == "One Time":
		repayment_periods = 1

	if rate_of_interest:
		monthly_interest_rate = flt(rate_of_interest) / (get_frequency(frequency) * 100)
		monthly_repayment_amount = (
			loan_amount * monthly_interest_rate * (1 + monthly_interest_rate) ** repayment_periods
		) / ((1 + monthly_interest_rate) ** repayment_periods - 1)
	else:
		monthly_repayment_amount = math.ceil(flt(loan_amount) / repayment_periods)

	if ceil_monthly_repayment:
		monthly_repayment_amount = math.ceil(monthly_repayment_amount)
	else:
		monthly_repayment_amount = flt(monthly_repayment_amount)
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
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if additional_principal_amount:
		current_balance_amount = additional_principal_amount
		additional_principal_amount = 0
	else:
		current_balance_amount = balance_amount

	interest_amount = flt(
		current_balance_amount * flt(rate_of_interest) * days / (months * 100), precision
	)

	principal_amount = monthly_repayment_amount - flt(interest_amount)

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


def get_ceil_monthly_repayment(loan=None, loan_product=None):
	# The below query fetches the flag from Loan Product directly.
	# I think this is easier and more straightforward than creating
	# a chain of docs with redundant values
	# (Loan Product -> Loan -> Loan Repayment)

	loan_product_doc = frappe.query_builder.DocType("Loan Product")
	loan_doc = frappe.query_builder.DocType("Loan")

	query = frappe.qb.from_(loan_product_doc).select(loan_product_doc.ceil_monthly_repayment)
	if loan:
		loan_query = frappe.qb.from_(loan_doc).where(loan_doc.name == loan).select(loan_doc.loan_product)
		query = query.where(loan_product_doc.name == loan_query)
	if loan_product:
		query = query.where(loan_product_doc.name == loan_product)
	ceil_monthly_repayment = query.run()[0][0]
	return ceil_monthly_repayment
