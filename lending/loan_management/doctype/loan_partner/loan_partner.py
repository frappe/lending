# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document


class LoanPartner(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def validate(self):
		self.validate_percentage_and_interest_fields()

	def validate_percentage_and_interest_fields(self):
		fields = [
			"partner_loan_share_percentage",
			"company_loan_share_percentage",
			"partner_base_interest_rate",
			"company_base_interest_rate",
			"fldg_total_percentage",
			"fldg_fixed_deposit_percentage",
			"fldg_corporate_guarantee_percentage",
		]

		for field in fields:
			if self.get(field) and (self.get(field) < 1 or self.get(field) > 99):
				frappe.throw(_("{0} should be between 1 and 99").format(frappe.bold(frappe.unscrub(field))))

		shareables_fields = [
			"partner_collection_percentage",
			"company_collection_percentage",
			"partner_loan_amount_percentage",
			"minimum_partner_loan_amount_percentage",
		]

		for shareable in self.shareables:
			for field in shareables_fields:
				if shareable.get(field) and (shareable.get(field) < 1 or shareable.get(field) > 99):
					frappe.throw(
						_("Row {0}: {1} should be between 1 and 99").format(
							shareable.idx, frappe.bold(frappe.unscrub(field))
						)
					)
