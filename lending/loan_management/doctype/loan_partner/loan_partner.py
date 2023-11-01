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
			if self.get(field) and (self.get(field) < 0 or self.get(field) > 100):
				frappe.throw(_("{0} should be between 0 and 100").format(frappe.bold(frappe.unscrub(field))))
