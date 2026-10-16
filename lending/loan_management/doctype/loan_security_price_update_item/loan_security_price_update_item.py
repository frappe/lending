# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LoanSecurityPriceUpdateItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		loan_security: DF.Link
		loan_security_name: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		previous_price: DF.Link | None
		previous_valid_upto: DF.Datetime | None
		price: DF.Currency
		remarks: DF.Data | None
	# end: auto-generated types

	pass
