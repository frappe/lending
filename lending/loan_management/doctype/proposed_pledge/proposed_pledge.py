# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


# import frappe
from frappe.model.document import Document


class ProposedPledge(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		haircut: DF.Percent
		loan_security: DF.Link | None
		loan_security_name: DF.Data | None
		loan_security_price: DF.Currency
		mutual_fund_holding: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		post_haircut_amount: DF.Currency
		purchase_date: DF.Date | None
		qty: DF.Float
	# end: auto-generated types

	pass
