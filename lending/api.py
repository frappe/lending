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
def get_due_details(loan: str, as_on_date: str, loan_disbursement: str | None = None) -> dict:
	"""
	API to get due details for a given loan account as on a specific date
	"""

	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	amounts = calculate_amounts(loan, as_on_date, loan_disbursement=loan_disbursement)

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

@frappe.whitelist()
def apply_charge(loan: str, charge_type: str, based_on: str, percentage: float | None = None, amount: float | None = None, charge_applicable_date: str | None = None):
	from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
	from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
		make_sales_invoice_for_charge,
	)
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		calculate_amounts,
		get_pending_principal_amount,
	)
	from lending.loan_management.utils import create_charge_master, loan_accounting_enabled

	create_charge_master(charge_type)

	if based_on == "On Outstanding Principal":
		loan_doc = frappe.get_doc("Loan", loan)
		pending_principal_amount = get_pending_principal_amount(loan_doc)
		charge_amount = (pending_principal_amount * percentage) / 100
	elif based_on == "On Total Payable Amount":
		payable_amount = calculate_amounts(loan, getdate(), payment_type="Loan Closure").get("payable_amount")
		charge_amount = (payable_amount * percentage) / 100
	elif based_on == "Flat":
		charge_amount = amount

	loan_details = frappe.db.get_value("Loan", loan, ["company", "applicant", "applicant_type"], as_dict=1)

	if loan_accounting_enabled(loan_details.company):
		charges = [
			{
				"charge": charge_type,
				"amount": charge_amount,
			}
		]
		make_sales_invoice_for_charge(loan, None, None, charge_type, charge_amount, charge_applicable_date, loan_details.company, charges)
	else:
		create_loan_demand(
			loan=loan,
			demand_date=getdate(charge_applicable_date),
			demand_type="Charges",
			demand_subtype=charge_type,
			amount=charge_amount,
		)

	frappe.response["message"] = _("Charge applied successfully for amount {0}").format(charge_amount)