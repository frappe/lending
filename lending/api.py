# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate


@frappe.whitelist()
def get_repayment_schedule(loan_product: str, loan_amount: float, rate_of_interest: float, tenure: int, repayment_frequency: str | None, repayment_start_date: str | None = None) -> list[dict]:
	"""
	API to get the repayment schedule for given loan product and repayment frequency
	"""

	repayment_schedule = frappe.new_doc("Loan Repayment Schedule")
	repayment_schedule.loan_product = loan_product
	repayment_schedule.repayment_frequency = repayment_frequency or "Monthly"
	repayment_schedule.repayment_method = "Repay Over Number of Periods"
	repayment_schedule.repayment_periods = tenure
	repayment_schedule.rate_of_interest = rate_of_interest
	repayment_schedule.posting_date = getdate()
	repayment_schedule.repayment_start_date = getdate(repayment_start_date)
	repayment_schedule.loan_amount = loan_amount
	repayment_schedule.current_principal_amount = loan_amount
	repayment_schedule.moratorium_tenure = 0
	repayment_schedule.moratorium_type = ""

	repayment_schedule.repayment_schedule_type = frappe.db.get_value("Loan Product", loan_product, "repayment_schedule_type")
	repayment_schedule.validate()

	response = {
		"loan_amount": repayment_schedule.loan_amount,
		"rate_of_interest": repayment_schedule.rate_of_interest,
		"tenure": tenure,
		"repayment_start_date": repayment_schedule.repayment_start_date,
		"repayment_periods": []
	}

	for row in repayment_schedule.get("repayment_schedule"):
		response["repayment_periods"].append({
			"payment_date": row.payment_date,
			"principal_amount": flt(row.principal_amount, 2),
			"interest_amount": flt(row.interest_amount, 2),
			"total_payment": flt(row.total_payment, 2),
			"balance_loan_amount": flt(row.balance_loan_amount, 2)
		})

	frappe.response["message"] = response

@frappe.whitelist()
def update_loan_security_price(data: dict):
	"""
	API to bulk update loan security price
	Note this API assumes only one record exists for updating loan securities
	"""

	if isinstance(data, str):
		data = json.loads(data)

	for loan_security, price_details in data.items():
		frappe.db.set_value("Loan Security Price", {"loan_security": loan_security}, {
			"loan_security_price": price_details.get("loan_security_price"),
			"valid_from": price_details.get("valid_from"),
			"valid_upto": price_details.get("valid_upto")
		})

	frappe.response["message"] = _("Loan Security Prices updated successfully")

@frappe.whitelist()
def get_due_details(loan: str, as_on_date: str) -> dict:
	"""
	API to get due details for a given loan account as on a specific date
	"""

	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	amounts = calculate_amounts(loan, as_on_date)

	frappe.response["message"] = {
		"overdue_penalty_amount": amounts.get("penalty_amount"),
		"overdue_interest_amount": amounts.get("interest_amount"),
		"overdue_principal_amount": amounts.get("payable_principal_amount"),
		"principal_outstanding": amounts.get("pending_principal_amount"),
		"overdue_total_amount": amounts.get("payable_amount"),
		"applicable_future_interest": amounts.get("unaccrued_interest"),
		"unbooked_interest": amounts.get("unbooked_interest"),
		"applicable_future_penalty": amounts.get("unbooked_penalty"),
		"oldest_due_date": amounts.get("due_date"),
		"overdue_charges": amounts.get("total_charges_payable"),
		"available_security_deposit": amounts.get("available_security_deposit"),
		"written_off_amount": amounts.get("written_off_amount"),
		"excess_amount_paid": amounts.get("excess_amount_paid")
	}