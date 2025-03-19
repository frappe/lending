# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanPartnerShareable(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company_collection_percentage: DF.Percent
		minimum_partner_loan_amount_percentage: DF.Percent
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		partner_collection_percentage: DF.Percent
		partner_loan_amount_percentage: DF.Percent
		shareable_type: DF.Link
		sharing_parameter: DF.Literal["", "Collection Percentage", "Loan Amount Percentage"]
	# end: auto-generated types

	pass
