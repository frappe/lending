# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanCharges(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		charge_based_on: DF.Literal["Percentage", "Fixed Amount"]
		charge_type: DF.Link | None
		income_account: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		percentage: DF.Percent
		receivable_account: DF.Link | None
		suspense_account: DF.Link | None
		waiver_account: DF.Link | None
		write_off_account: DF.Link | None
	# end: auto-generated types

	pass
