# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LoanSecuritySaleRepayment(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		loan_disbursement: DF.Link | None
		loan_repayment: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		repayment_type: DF.Data | None
	# end: auto-generated types

	pass
