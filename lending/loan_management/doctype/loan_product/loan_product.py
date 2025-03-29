# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document


class LoanProduct(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_charges.loan_charges import LoanCharges
		from lending.loan_management.doctype.loan_product_loan_partner.loan_product_loan_partner import (
			LoanProductLoanPartner,
		)

		additional_interest_accrued: DF.Link | None
		additional_interest_income: DF.Link | None
		additional_interest_receivable: DF.Link | None
		additional_interest_suspense: DF.Link | None
		additional_interest_waiver: DF.Link | None
		amended_from: DF.Link | None
		broken_period_interest_recovery_account: DF.Link
		collection_offset_sequence_for_settlement_collection: DF.Link | None
		collection_offset_sequence_for_standard_asset: DF.Link | None
		collection_offset_sequence_for_sub_standard_asset: DF.Link | None
		collection_offset_sequence_for_written_off_asset: DF.Link | None
		company: DF.Link
		customer_refund_account: DF.Link
		cyclic_day_of_the_month: DF.Int
		days_past_due_threshold_for_npa: DF.Int
		disabled: DF.Check
		disbursement_account: DF.Link
		excess_amount_acceptance_limit: DF.Float
		grace_period_in_days: DF.Int
		interest_accrued_account: DF.Link
		interest_income_account: DF.Link
		interest_receivable_account: DF.Link
		interest_waiver_account: DF.Link
		is_term_loan: DF.Check
		loan_account: DF.Link
		loan_category: DF.Link | None
		loan_charges: DF.Table[LoanCharges]
		loan_partners: DF.TableMultiSelect[LoanProductLoanPartner]
		maximum_loan_amount: DF.Currency
		min_days_bw_disbursement_first_repayment: DF.Int
		payment_account: DF.Link
		penalty_accrued_account: DF.Link
		penalty_income_account: DF.Link
		penalty_interest_rate: DF.Percent
		penalty_receivable_account: DF.Link
		penalty_suspense_account: DF.Link | None
		penalty_waiver_account: DF.Link
		product_code: DF.Data
		product_name: DF.Data
		rate_of_interest: DF.Percent
		repayment_date_on: DF.Literal["", "Start of the next month", "End of the current month"]
		repayment_schedule_type: DF.Literal[
			"",
			"Monthly as per repayment start date",
			"Pro-rated calendar months",
			"Monthly as per cycle date",
			"Line of Credit",
		]
		same_as_regular_interest_accounts: DF.Check
		security_deposit_account: DF.Link
		subsidy_adjustment_account: DF.Link | None
		suspense_collection_account: DF.Link | None
		suspense_interest_income: DF.Link | None
		validate_normal_repayment: DF.Check
		write_off_account: DF.Link
		write_off_amount: DF.Currency
		write_off_recovery_account: DF.Link
	# end: auto-generated types

	def before_validate(self):
		self.set_missing_values()

	def validate(self):
		self.validate_accounts()
		self.validate_rates()

	def set_missing_values(self):
		company_min_days_bw_disbursement_first_repayment = frappe.get_cached_value(
			"Company", self.company, "min_days_bw_disbursement_first_repayment"
		)
		if (
			self.min_days_bw_disbursement_first_repayment is None
			and company_min_days_bw_disbursement_first_repayment
		):
			self.min_days_bw_disbursement_first_repayment = company_min_days_bw_disbursement_first_repayment

	def validate_accounts(self):
		for fieldname in [
			"payment_account",
			"loan_account",
			"interest_income_account",
			"penalty_income_account",
		]:
			company = frappe.get_value("Account", self.get(fieldname), "company")

			if company and company != self.company:
				frappe.throw(
					_("Account {0} does not belong to company {1}").format(
						frappe.bold(self.get(fieldname)), frappe.bold(self.company)
					)
				)

		if self.get("loan_account") == self.get("payment_account"):
			frappe.throw(_("Loan Account and Payment Account cannot be same"))

	def validate_rates(self):
		for field in ["rate_of_interest", "penalty_interest_rate"]:
			if self.get(field) and self.get(field) < 0:
				frappe.throw(_("{0} cannot be negative").format(frappe.unscrub(field)))


@frappe.whitelist()
def get_default_charge_accounts(charge_type, company):
	default_charge_accounts = frappe.db.get_value(
		"Item Default",
		{"parent": charge_type, "company": company},
		[
			"income_account",
			"default_receivable_account",
			"default_waiver_account",
			"default_write_off_account",
			"default_suspense_account",
		],
		as_dict=True,
	)
	out = {
		"income_account": default_charge_accounts.income_account,
		"receivable_account": default_charge_accounts.default_receivable_account,
		"waiver_account": default_charge_accounts.default_waiver_account,
		"write_off_account": default_charge_accounts.default_write_off_account,
		"suspense_account": default_charge_accounts.default_suspense_account,
	}

	return out
