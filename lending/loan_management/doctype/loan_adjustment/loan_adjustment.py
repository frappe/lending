# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_restructure.loan_restructure import create_loan_repayment


class LoanAdjustment(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_adjustment_detail.loan_adjustment_detail import (
			LoanAdjustmentDetail,
		)

		adjustments: DF.Table[LoanAdjustmentDetail]
		amended_from: DF.Link | None
		foreclosure_type: DF.Literal["", "Manual Foreclosure", "Internal Foreclosure"]
		loan: DF.Link
		loan_disbursement: DF.Link | None
		payment_account: DF.Link | None
		posting_date: DF.Datetime
	# end: auto-generated types

	def validate(self):
		amounts = calculate_amounts(self.loan, self.posting_date)

		if self.get("foreclosure_type"):
			repayment_types = [repayment.loan_repayment_type for repayment in self.get("adjustments")]
			if "Security Deposit Adjustment" not in repayment_types:
				self.append(
					"adjustments",
					{
						"loan_repayment_type": "Security Deposit Adjustment",
						"amount": amounts.get("available_security_deposit", 0),
					},
				)

		available_sd = float(amounts.get("available_security_deposit") or 0)

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		total_net_payable = round(
			float(amounts.get("unaccrued_interest") or 0)
			+ float(amounts.get("interest_amount") or 0)
			+ float(amounts.get("penalty_amount") or 0)
			+ float(amounts.get("total_charges_payable") or 0)
			- float(amounts.get("available_security_deposit") or 0)
			+ float(amounts.get("unbooked_interest") or 0)
			+ float(amounts.get("unbooked_penalty") or 0)
			+ float(amounts.get("pending_principal_amount") or 0),
			precision,
		)

		total_adjustment_amount = 0.0

		for row in self.adjustments:
			if not row.amount:
				continue

			amount = float(row.amount)
			if row.loan_repayment_type != "Security Deposit Adjustment":
				total_adjustment_amount += amount

		if total_adjustment_amount > total_net_payable:
			frappe.throw(
				_(
					"Total adjustment amount ({0}) exceeds the total net payable ({1}). You can only adjust up to {1}."
				).format(total_adjustment_amount, total_net_payable)
			)

	def on_submit(self):
		for repayment in self.get("adjustments"):
			if repayment.amount:
				create_loan_repayment(
					self.loan,
					self.posting_date,
					repayment.loan_repayment_type,
					repayment.amount,
					adjustment_name=self.name,
					payment_account=self.payment_account,
					loan_disbursement=self.loan_disbursement,
				)
