# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


# import frappe
from frappe.model.document import Document


class LoanRepaymentDetail(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		demand_subtype: DF.Data | None
		demand_type: DF.Data | None
		loan_demand: DF.Link | None
		paid_amount: DF.Currency
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		partner_share: DF.Currency
		sales_invoice: DF.Link | None
	# end: auto-generated types

	pass
