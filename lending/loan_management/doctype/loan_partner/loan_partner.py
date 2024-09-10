# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document


class LoanPartner(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def validate(self):
		self.validate_percentage_and_interest_fields()
		self.validate_shareables()

	def validate_percentage_and_interest_fields(self):
		fields = ["partner_loan_share_percentage", "partner_base_interest_rate"]

		for field in fields:
			if not self.get(field) or self.get(field) < 1 or self.get(field) > 99:
				frappe.throw(_("{0} should be between 1 and 99").format(frappe.bold(frappe.unscrub(field))))

		fldg_fields_to_validate = []

		if self.type_of_fldg_applicable == "Fixed Deposit Only":
			fldg_fields_to_validate = ["fldg_fixed_deposit_percentage"]
		elif self.type_of_fldg_applicable == "Corporate Guarantee Only":
			fldg_fields_to_validate = ["fldg_corporate_guarantee_percentage"]
		elif self.type_of_fldg_applicable == "Both Fixed Deposit and Corporate Guarantee":
			fldg_fields_to_validate = [
				"fldg_fixed_deposit_percentage",
				"fldg_corporate_guarantee_percentage",
			]

		for field in fldg_fields_to_validate:
			if not self.get(field) or self.get(field) < 1 or self.get(field) > 99:
				frappe.throw(_("{0} should be between 1 and 99").format(frappe.bold(frappe.unscrub(field))))

	def validate_shareables(self):
		shareables = []

		for shareable in self.shareables:
			if shareable.shareable_type not in shareables:
				shareables.append(shareable.shareable_type)
			else:
				frappe.throw(
					_("Shareable Type {0} added multiple times").format(frappe.bold(shareable.shareable_type))
				)

			if shareable.sharing_parameter == "Collection Percentage":
				for field in ["partner_collection_percentage", "company_collection_percentage"]:
					if not shareable.get(field) or shareable.get(field) < 1 or shareable.get(field) > 99:
						frappe.throw(
							_("Row {0}: {1} should be between 1 and 99").format(
								shareable.idx, frappe.bold(frappe.unscrub(field))
							)
						)
				for field in ["partner_loan_amount_percentage", "minimum_partner_loan_amount_percentage"]:
					if shareable.get(field):
						shareable.set(field, 0)
			elif shareable.sharing_parameter == "Loan Amount Percentage":
				if (
					not shareable.get("partner_loan_amount_percentage")
					or shareable.get("partner_loan_amount_percentage") < 1
					or shareable.get("partner_loan_amount_percentage") > 99
				):
					frappe.throw(
						_("Row {0}: {1} should be between 1 and 99").format(
							shareable.idx, frappe.bold(frappe.unscrub("partner_loan_amount_percentage"))
						)
					)
				if shareable.get("minimum_partner_loan_amount_percentage") and (
					shareable.get("minimum_partner_loan_amount_percentage") < 1
					or shareable.get("minimum_partner_loan_amount_percentage") > 99
				):
					frappe.throw(
						_("Row {0}: {1} should be between 1 and 99").format(
							shareable.idx, frappe.bold(frappe.unscrub("minimum_partner_loan_amount_percentage"))
						)
					)
				for field in ["partner_collection_percentage", "company_collection_percentage"]:
					if shareable.get(field):
						shareable.set(field, 0)


@frappe.whitelist()
def get_colender_payout_details(posting_date):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_bulk_due_details

	partner_accounts = get_partner_accounts()
	accounts, account_map = get_account_details_and_map(partner_accounts)
	payable_balances = get_payable_balances(posting_date, accounts)
	loans = [d.against_voucher for d in payable_balances]

	bulk_due_details = get_bulk_due_details(loans, posting_date)
	bulk_due_map = {}

	for due in bulk_due_details:
		bulk_due_map[due.get("loan")] = due

	partner_map = get_partner_map(loans)
	fldg_date_map = get_fldg_date_map(loans)

	data = {}
	for payable_balance in payable_balances:
		dues = bulk_due_map.get(payable_balance.against_voucher, {})
		principal_outstanding = dues.get("pending_principal_amount")
		interest_accrued = dues.get("interest_accrued")
		interest_overdue = dues.get("interest_amount")
		penalty_overdue = dues.get("penalty_amount")
		charge_overdue = dues.get("total_charges_payable")
		fldg_date = fldg_date_map.get(payable_balance.against_voucher)

		data.setdefault(
			payable_balance.against_voucher,
			get_initial_balances(
				principal_outstanding,
				interest_accrued,
				interest_overdue,
				penalty_overdue,
				charge_overdue,
				fldg_date,
			),
		)

		loan_partner = partner_map.get(payable_balance.against_voucher)

		row = data[payable_balance.against_voucher]
		if loan_partner:
			partner_details = account_map.get(loan_partner)

			account_type = get_account_type(partner_details, payable_balance.account)
			if account_type == "FLDG":
				row["payable_fldg_balance"] += payable_balance.debit - payable_balance.credit
				row["amount_invoked"] += payable_balance.debit
				row["amount_paid"] += payable_balance.credit
			elif account_type == "Credit":
				row["payable_principal"] += payable_balance.debit - payable_balance.credit
				row["payable_emi"] += payable_balance.debit - payable_balance.credit
				row["total_payable"] += payable_balance.debit - payable_balance.credit
			elif account_type == "Interest":
				row["payable_interest"] += payable_balance.debit - payable_balance.credit
				row["payable_emi"] += payable_balance.debit - payable_balance.credit
				row["total_payable"] += payable_balance.debit - payable_balance.credit

	result = []
	for loan, values in data.items():
		values["loan_partner"] = partner_map.get(loan)
		values["loan"] = loan
		result.append(values)

	return result


def get_initial_balances(
	principal_outstanding,
	interest_accrued,
	interest_overdue,
	penalty_overdue,
	charge_overdue,
	fldg_date,
):
	total_overdue = interest_overdue + penalty_overdue + charge_overdue
	return {
		"payable_fldg_balance": 0.0,
		"payable_interest": 0.0,
		"payable_principal": 0.0,
		"payable_emi": 0.0,
		"total_payable": 0.0,
		"principal_outstanding": principal_outstanding,
		"interest_accrued": interest_accrued,
		"interest_overdue": interest_overdue,
		"penalty_overdue": penalty_overdue,
		"charge_overdue": charge_overdue,
		"total_overdue": total_overdue,
		"amount_invoked": 0.0,
		"amount_paid": 0.0,
		"fldg_trigger_date": fldg_date,
	}


def get_payable_balances(posting_date, accounts):
	payable_balances = frappe.db.get_all(
		"GL Entry",
		filters={
			"posting_date": ("<=", posting_date),
			"account": ("in", accounts),
			"voucher_type": ("!=", "Loan Disbursement"),
		},
		fields=["against_voucher", "account", "sum(debit) as debit", "sum(credit) as credit"],
		group_by="against_voucher, account",
	)

	return payable_balances


def get_account_details_and_map(partner_accounts):
	accounts = []
	account_map = {}

	for account_detail in partner_accounts:

		if account_detail.fldg_account:
			accounts.append(account_detail.fldg_account)

		if account_detail.credit_account:
			accounts.append(account_detail.credit_account)

		if account_detail.partner_interest_share:
			accounts.append(account_detail.partner_interest_share)

		account_map[account_detail.name] = {
			"partner_interest_share": account_detail.partner_interest_share,
			"fldg_account": account_detail.fldg_account,
			"credit_account": account_detail.credit_account,
		}

	return accounts, account_map


def get_partner_accounts():
	return frappe.get_all(
		"Loan Partner", fields=["fldg_account", "credit_account", "partner_interest_share", "name"]
	)


def get_partner_map(loans):
	return frappe._dict(
		frappe.db.get_all(
			"Loan", filters={"name": ("in", loans)}, fields=["name", "loan_partner"], as_list=True
		)
	)


def get_fldg_date_map(loans):
	return frappe._dict(
		frappe.db.get_all(
			"Loan", filters={"name": ("in", loans)}, fields=["name", "fldg_trigger_date"], as_list=True
		)
	)


def get_account_type(colender_details, account):
	if account == colender_details.get("fldg_account"):
		return "FLDG"
	elif account == colender_details.get("credit_account"):
		return "Credit"
	elif account == colender_details.get("partner_interest_share"):
		return "Interest"
