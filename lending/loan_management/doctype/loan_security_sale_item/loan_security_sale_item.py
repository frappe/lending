# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LoanSecuritySaleItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		expected_price: DF.Currency
		loan_security: DF.Link
		loan_security_name: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pledged_qty: DF.Float
		proceeds: DF.Currency
		qty: DF.Float
		sale_price: DF.Currency
		sold_qty: DF.Float
	# end: auto-generated types

	pass
