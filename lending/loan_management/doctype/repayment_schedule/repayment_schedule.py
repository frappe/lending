# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


# import frappe
from frappe.model.document import Document


class RepaymentSchedule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		balance_loan_amount: DF.Currency
		demand_generated: DF.Check
		interest_amount: DF.Currency
		number_of_days: DF.Int
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		payment_date: DF.Date | None
		principal_amount: DF.Currency
		total_payment: DF.Currency
	# end: auto-generated types

	pass
