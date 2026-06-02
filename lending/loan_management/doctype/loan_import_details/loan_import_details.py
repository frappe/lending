# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanImportDetails(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		disbursed_amount: DF.Currency
		disbursement_date: DF.Date | None
		loan_disbursement_id: DF.Data | None
		opening_additional_outstanding: DF.Currency
		opening_charge_outstanding: DF.Currency
		opening_interest_outstanding: DF.Currency
		opening_penalty_outstanding: DF.Currency
		opening_principal_outstanding: DF.Currency
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		repayment_frequency: DF.Literal["", "Monthly", "Daily", "Weekly", "Bi-Weekly", "Quarterly", "One Time"]
		repayment_method: DF.Literal["", "Repay Over Number of Periods", "Repay Fixed Amount per Period"]
		repayment_periods: DF.Int
		repayment_start_date: DF.Date | None
	# end: auto-generated types

	pass
