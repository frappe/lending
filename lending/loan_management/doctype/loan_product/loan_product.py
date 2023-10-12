# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document


class LoanProduct(Document):
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
