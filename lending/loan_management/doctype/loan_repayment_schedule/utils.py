import frappe
from frappe.utils import add_months, cint, flt

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	get_interest_amount,
)


def get_monthly_repayment_schedule(
	loan_amount,
	rate_of_interest,
	repayment_periods,
	frequency,
	ceil_monthly_repayment=False,
	disbursement_date=None,
	repayment_start_date=None,
	interest_day_count_convention=False,
):
	if frequency == "One Time":
		repayment_periods = 1

	monthly_repayment_schedule = binary_search_monthly_repayment_schedule_for_fixed_number_of_periods(
		principal=loan_amount,
		repayment_periods=repayment_periods,
		rate_of_interest=rate_of_interest,
		disbursement_date=disbursement_date,
		repayment_start_date=repayment_start_date,
		interest_day_count_convention=interest_day_count_convention,
		ceil_monthly_repayment=ceil_monthly_repayment,
	)

	return monthly_repayment_schedule


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


def binary_search_monthly_repayment_schedule_for_fixed_number_of_periods(
	principal,
	repayment_periods,
	rate_of_interest,
	disbursement_date,
	repayment_start_date,
	interest_day_count_convention,
	ceil_monthly_repayment=False,
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2
	l = 0
	h = principal**2  # just to be safe
	for i in range(300):
		x = (l + h) / 2
		remaining_principal = repayment_simulator(
			x,
			principal,
			repayment_periods,
			rate_of_interest,
			disbursement_date,
			repayment_start_date,
			interest_day_count_convention,
			ceil_monthly_repayment,
		)
		if abs(remaining_principal) < 0.0001:
			_, schedule = repayment_simulator(
				x,
				principal,
				repayment_periods,
				rate_of_interest,
				disbursement_date,
				repayment_start_date,
				interest_day_count_convention,
				generate_schedule=True,
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
	rate_of_interest,
	disbursement_date,
	repayment_start_date,
	interest_day_count_convention,
	repayment_periods=None,
	generate_schedule=False,
):
	# list initialisation takes up resources
	if generate_schedule:
		schedule = []
	prev_date = disbursement_date
	current_date = repayment_start_date
	i = 0
	repay_over_number_of_periods = repayment_method == "Repay Over Number of Periods"
	while True:
		i += 1
		interest_amount = get_interest_amount(
			principal_amount=principal,
			rate_of_interest=rate_of_interest,
			from_date=prev_date,
			to_date=current_date,
			interest_day_count_convention=interest_day_count_convention,
		)

		principal -= monthly_repayment_amount - interest_amount

		if generate_schedule:
			schedule.append(
				frappe._dict(
					{
						"principal_amount": principal,
						"posting_date": current_date,
						"interest_amount": interest_amount,
					}
				)
			)

		if repay_over_number_of_periods:
			if i == repayment_periods:
				break
		prev_date = current_date
		current_date = add_months(current_date, 1)

	if generate_schedule:
		return principal, schedule
	return principal
