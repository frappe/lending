# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class LoanLead(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		address: DF.Link | None
		age: DF.Int
		amended_from: DF.Link | None
		applicant_name: DF.Data
		applicant_type: DF.Literal["Individual", "Business"]
		company_name: DF.Data | None
		contact: DF.Link | None
		date_of_birth: DF.Date | None
		email: DF.Data
		email_otp: DF.Password | None
		email_verification_status: DF.Literal["Pending", "Initiated", "Verified"]
		employment_type: DF.Literal["Salaried", "Self-employed"]
		income: DF.Currency
		lead_source: DF.Data | None
		loan_amount: DF.Currency
		loan_product: DF.Link
		mobile_number: DF.Phone
		mobile_verification_status: DF.Literal["Pending", "Initiated", "Verified"]
		pan: DF.Data | None
		proposed_tenure: DF.Int
		sms_otp: DF.Password | None
		status: DF.Data | None
	# end: auto-generated types

	def validate(self):
		if self.applicant_type == "Individual":
			self.age = getdate().year - getdate(self.date_of_birth).year


@frappe.whitelist()
def convert_to_loan_application(loan_lead: Document):
	loan_application = frappe.new_doc("Loan Application")
	loan_application.applicant_email_address = loan_lead.email
	loan_application.applicant_name = loan_lead.applicant_name
	loan_application.applicant_phone_number = loan_lead.mobile_number
	loan_application.loan_product = loan_lead.loan_product
	loan_application.loan_amount = loan_lead.loan_amount
	loan_application.repayment_periods = loan_lead.proposed_tenure

	loan_application.save()