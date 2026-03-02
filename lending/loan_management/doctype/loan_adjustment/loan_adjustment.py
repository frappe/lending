# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

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
					position=0,
				)

			self.validate_foreclosure_adjustment(amounts)

	def validate_foreclosure_adjustment(self, amounts):
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		total_net_payable = flt(
			amounts.get("pending_principal_amount", 0)
			+ amounts.get("interest_amount", 0)
			+ amounts.get("penalty_amount", 0)
			+ amounts.get("unaccrued_interest", 0)
			+ amounts.get("unbooked_interest", 0)
			+ amounts.get("unbooked_penalty", 0)
			+ amounts.get("total_charges_payable", 0)
			- amounts.get("available_security_deposit", 0),
			precision,
		)

		adjustment_amount = flt(
			sum(
				flt(row.amount, precision)
				for row in self.adjustments
				if row.amount and row.loan_repayment_type != "Security Deposit Adjustment"
			),
			precision,
		)

		if total_net_payable > adjustment_amount:
			frappe.throw(
				_("Total net payable amount is {0}, but the total adjustment amount is {1}. "
				"For Manual or Internal Foreclosure, the adjustment amount must exactly match the total net payable amount.")
				.format(total_net_payable, adjustment_amount)
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
