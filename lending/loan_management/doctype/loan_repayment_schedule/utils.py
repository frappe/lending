from math import ceil

import frappe
from frappe.utils import add_days, add_months, add_years, cint, flt, get_last_day

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	get_interest_amount,
)


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


def get_repayment_schedule(
	principal,
	rate_of_interest,
	repayment_method,
	frequency,
	disbursement_date,
	repayment_start_date,
	interest_day_count_convention,
	ceil_monthly_repayment=False,
	repayment_periods=-1,
):
	if frequency == "One Time":
		repayment_periods = 1
	precision = cint(frappe.db.get_default("currency_precision")) or 2
	l = 0
	h = principal**2  # just to be safe
	for _ in range(300):
		x = (l + h) / 2
		remaining_principal = repayment_simulator(
			monthly_repayment_amount=x,
			principal=principal,
			rate_of_interest=rate_of_interest,
			repayment_method=repayment_method,
			frequency=frequency,
			disbursement_date=disbursement_date,
			repayment_start_date=repayment_start_date,
			interest_day_count_convention=interest_day_count_convention,
			ceil_monthly_repayment=ceil_monthly_repayment,
			repayment_periods=repayment_periods,
			precision=precision,
		)
		if flt(remaining_principal, precision):
			_, schedule = repayment_simulator(
				monthly_repayment_amount=x,
				principal=principal,
				rate_of_interest=rate_of_interest,
				frequency=frequency,
				repayment_method=repayment_method,
				disbursement_date=disbursement_date,
				repayment_start_date=repayment_start_date,
				interest_day_count_convention=interest_day_count_convention,
				repayment_periods=repayment_periods,
				ceil_monthly_repayment=ceil_monthly_repayment,
				generate_schedule=True,
				precision=precision,
			)
			return x, schedule
		if remaining_principal < 0:
			h = x
		else:
			l = x
	frappe.throw("There was an error finding the monthly repayment amount (binary search stuck)")


def repayment_simulator(
	monthly_repayment_amount,
	principal,
	repayment_method,
	frequency,
	rate_of_interest,
	disbursement_date,
	repayment_start_date,
	interest_day_count_convention,
	repayment_periods=-1,
	ceil_monthly_repayment=False,
	generate_schedule=False,
	precision=2,
):
	# list initialisation takes up resources
	if generate_schedule:
		schedule = []
	is_last_day = get_last_day(repayment_start_date) == repayment_start_date
	prev_date = disbursement_date
	current_date = repayment_start_date
	i = 0
	repay_over_number_of_periods = repayment_method == "Repay Over Number of Periods"
	while True:
		interest_amount = get_interest_amount(
			principal_amount=principal,
			rate_of_interest=rate_of_interest,
			from_date=prev_date,
			to_date=current_date,
			interest_day_count_convention=interest_day_count_convention,
		)

		if ceil_monthly_repayment:
			monthly_repayment_amount = ceil(monthly_repayment_amount)
		diff = monthly_repayment_amount - interest_amount

		if flt(diff - principal, precision) > 0:
			monthly_repayment_amount = principal
			principal = 0
		else:
			principal -= diff

		if generate_schedule:
			schedule.append(
				frappe._dict(
					{
						"principal_amount": principal,
						"posting_date": current_date,
						"interest_amount": interest_amount,
						"repayment_amount": monthly_repayment_amount,
					}
				)
			)

		i += 1
		if repay_over_number_of_periods:
			if i == repayment_periods:
				break
		else:
			if principal == 0:
				break

		prev_date = current_date

		# ideally, for "One Time" frequency, the loop should have broken by now
		# so not defined here
		match frequency:
			case "Daily":
				current_date = add_days(current_date, 1)
			case "Weekly":
				current_date = add_days(current_date, 7)
			case "Monthly":
				if is_last_day:
					current_date = get_last_day(add_months(current_date, 1))
				else:
					current_date = add_months(current_date, 1)
			case "Quarterly":
				if is_last_day:
					current_date = get_last_day(add_months(current_date, 3))
				else:
					current_date = add_months(current_date, 3)
			case "Yearly":
				current_date = add_years(current_date, 1)

	if generate_schedule:
		return principal, schedule
	return principal
