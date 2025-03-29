# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanSecurityDeposit(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allocated_amount: DF.Currency
		allocated_date: DF.Date | None
		amended_from: DF.Link | None
		available_amount: DF.Currency
		deposit_amount: DF.Currency
		deposit_date: DF.Date | None
		loan: DF.Link | None
		loan_disbursement: DF.Link | None
		refund_amount: DF.Currency
		refund_date: DF.Date | None
	# end: auto-generated types

	pass
