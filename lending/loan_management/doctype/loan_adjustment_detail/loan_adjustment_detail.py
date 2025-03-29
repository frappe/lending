# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanAdjustmentDetail(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		loan_repayment_type: DF.Literal[
			"Normal Repayment",
			"Interest Waiver",
			"Penalty Waiver",
			"Charges Waiver",
			"Principal Capitalization",
			"Interest Capitalization",
			"Charges Capitalization",
			"Penalty Capitalization",
			"Principal Adjustment",
			"Interest Adjustment",
			"Interest Carry Forward",
			"Loan Closure",
			"Security Deposit Adjustment",
		]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	pass
