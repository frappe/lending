# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt, getdate


def compute_emi_preview(loan_product, loan_amount, rate_of_interest, repayment_periods, posting_date=None):
	if not (loan_product and loan_amount and rate_of_interest and repayment_periods):
		return 0

	schedule = frappe.new_doc("Loan Repayment Schedule")
	schedule.loan_product = loan_product
	schedule.repayment_frequency = "Monthly"
	schedule.repayment_method = "Repay Over Number of Periods"
	schedule.repayment_periods = repayment_periods
	schedule.rate_of_interest = rate_of_interest
	schedule.posting_date = getdate()
	schedule.repayment_start_date = getdate(posting_date)
	schedule.loan_amount = loan_amount
	schedule.current_principal_amount = loan_amount
	schedule.moratorium_tenure = 0
	schedule.moratorium_type = ""
	schedule.repayment_schedule_type = frappe.db.get_value("Loan Product", loan_product, "repayment_schedule_type")
	schedule.validate()

	if schedule.get("repayment_schedule"):
		return flt(schedule.repayment_schedule[0].total_payment, 2)
	return 0


def compute_dti_foir(monthly_income, existing_obligations, proposed_emi):
	monthly_income = flt(monthly_income)
	existing_obligations = flt(existing_obligations)
	proposed_emi = flt(proposed_emi)

	if not monthly_income:
		return 0, 0

	dti_ratio = (existing_obligations / monthly_income) * 100
	foir_ratio = ((existing_obligations + proposed_emi) / monthly_income) * 100

	return flt(dti_ratio, 2), flt(foir_ratio, 2)


def compute_ltv(loan_amount, proposed_pledges):
	loan_amount = flt(loan_amount)
	if not loan_amount or not proposed_pledges:
		return 0

	total_post_haircut = sum(flt(pledge.post_haircut_amount) for pledge in proposed_pledges)
	if not total_post_haircut:
		return 0

	return flt((loan_amount / total_post_haircut) * 100, 2)


def get_max_foir(loan_product):
	max_foir = frappe.db.get_value("Loan Product", loan_product, "max_foir")
	return flt(max_foir) or 50.0


def compute_eligibility_amount(
	monthly_income, existing_obligations, rate_of_interest, repayment_periods, loan_product
):
	monthly_income = flt(monthly_income)
	existing_obligations = flt(existing_obligations)
	rate_of_interest = flt(rate_of_interest)
	repayment_periods = flt(repayment_periods)

	if not monthly_income or not repayment_periods:
		return 0

	max_foir = get_max_foir(loan_product)
	max_total_obligation = monthly_income * max_foir / 100
	max_emi = max_total_obligation - existing_obligations

	if max_emi <= 0:
		return 0

	monthly_rate = rate_of_interest / (12 * 100)
	if not monthly_rate:
		return flt(max_emi * repayment_periods, 2)

	n = repayment_periods
	principal = max_emi * ((1 + monthly_rate) ** n - 1) / (monthly_rate * (1 + monthly_rate) ** n)

	return flt(principal, 2)
