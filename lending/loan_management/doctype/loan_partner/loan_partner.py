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
		self.validate_shareables()

	def validate_percentage_and_interest_fields(self):
		fields = [
			"partner_loan_share_percentage",
			"company_loan_share_percentage",
			"partner_base_interest_rate",
			"company_base_interest_rate",
		]

		for field in fields:
			if not self.get(field) or self.get(field) < 1 or self.get(field) > 99:
				frappe.throw(_("{0} should be between 1 and 99").format(frappe.bold(frappe.unscrub(field))))

		fldg_fields_to_validate = []

		if self.type_of_fldg_applicable == "Fixed Deposit only":
			fldg_fields_to_validate = ["fldg_fixed_deposit_percentage"]
		elif self.type_of_fldg_applicable == "Corporate Guarantee only":
			fldg_fields_to_validate = ["fldg_corporate_guarantee_percentage"]
		elif self.type_of_fldg_applicable == "Both Fixed Deposit and Corporate Guarantee":
			fldg_fields_to_validate = [
				"fldg_fixed_deposit_percentage",
				"fldg_corporate_guarantee_percentage",
			]

		for field in fldg_fields_to_validate:
			if not self.get(field) or self.get(field) < 1 or self.get(field) > 99:
				frappe.throw(_("{0} should be between 1 and 99").format(frappe.bold(frappe.unscrub(field))))

	def validate_shareables(self):
		shareables = []

		for shareable in self.shareables:
			if shareable.shareable_type not in shareables:
				shareables.append(shareable.shareable_type)
			else:
				frappe.throw(
					_("Shareable Type {0} added multiple times").format(frappe.bold(shareable.shareable_type))
				)

			if shareable.sharing_parameter == "Collection Percentage":
				for field in ["partner_collection_percentage", "company_collection_percentage"]:
					if not shareable.get(field) or shareable.get(field) < 1 or shareable.get(field) > 99:
						frappe.throw(
							_("Row {0}: {1} should be between 1 and 99").format(
								shareable.idx, frappe.bold(frappe.unscrub(field))
							)
						)
				for field in ["partner_loan_amount_percentage", "minimum_partner_loan_amount_percentage"]:
					if shareable.get(field):
						shareable.set(field, 0)
			elif shareable.sharing_parameter == "Loan Amount Percentage":
				if (
					not shareable.get("partner_loan_amount_percentage")
					or shareable.get("partner_loan_amount_percentage") < 1
					or shareable.get("partner_loan_amount_percentage") > 99
				):
					frappe.throw(
						_("Row {0}: {1} should be between 1 and 99").format(
							shareable.idx, frappe.bold(frappe.unscrub("partner_loan_amount_percentage"))
						)
					)
				if shareable.get("minimum_partner_loan_amount_percentage") and (
					shareable.get("minimum_partner_loan_amount_percentage") < 1
					or shareable.get("minimum_partner_loan_amount_percentage") > 99
				):
					frappe.throw(
						_("Row {0}: {1} should be between 1 and 99").format(
							shareable.idx, frappe.bold(frappe.unscrub("minimum_partner_loan_amount_percentage"))
						)
					)
				for field in ["partner_collection_percentage", "company_collection_percentage"]:
					if shareable.get(field):
						shareable.set(field, 0)
