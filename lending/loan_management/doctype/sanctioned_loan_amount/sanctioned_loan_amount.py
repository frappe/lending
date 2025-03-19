# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document


class SanctionedLoanAmount(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		applicant: DF.DynamicLink
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		company: DF.Link
		sanctioned_amount_limit: DF.Currency
	# end: auto-generated types

	def validate(self):
		sanctioned_doc = frappe.db.exists(
			"Sanctioned Loan Amount", {"applicant": self.applicant, "company": self.company}
		)

		if sanctioned_doc and sanctioned_doc != self.name:
			frappe.throw(
				_("Sanctioned Loan Amount already exists for {0} against company {1}").format(
					frappe.bold(self.applicant), frappe.bold(self.company)
				)
			)
