# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json
import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.query_builder import Criterion
from frappe.utils import cint, flt, rounded

from lending.loan_management.doctype.loan.loan import (
	get_sanctioned_amount_limit,
	get_total_loan_amount,
)
from lending.loan_management.doctype.loan_repayment_schedule.loan_repayment_schedule import (
	get_monthly_repayment_amount,
)
from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)


class LoanApplication(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.proposed_pledge.proposed_pledge import ProposedPledge
		from lending.loan_origination.doctype.loan_application_document.loan_application_document import (
			LoanApplicationDocument,
		)
		from lending.loan_origination.doctype.loan_co_applicants.loan_co_applicants import (
			LoanCoApplicants,
		)

		address_line_1: DF.Data | None
		address_line_2: DF.Data | None
		amended_from: DF.Link | None
		applicant: DF.DynamicLink | None
		applicant_email_address: DF.Data | None
		applicant_phone_number: DF.Phone | None
		applicant_type: DF.Literal["Employee", "Customer"]
		city: DF.Data | None
		co_applicants: DF.Table[LoanCoApplicants]
		company: DF.Link
		country: DF.Link | None
		description: DF.SmallText | None
		documents: DF.Table[LoanApplicationDocument]
		first_name: DF.Data | None
		is_secured_loan: DF.Check
		is_term_loan: DF.Check
		last_name: DF.Data | None
		loan_amount: DF.Currency
		loan_product: DF.Link
		maximum_loan_amount: DF.Currency
		posting_date: DF.Date
		proposed_pledges: DF.Table[ProposedPledge]
		rate_of_interest: DF.Percent
		repayment_amount: DF.Currency
		repayment_method: DF.Literal["", "Repay Fixed Amount per Period", "Repay Over Number of Periods"]
		repayment_periods: DF.Int
		state: DF.Data | None
		status: DF.Literal["Open", "Approved", "Rejected"]
		total_payable_amount: DF.Currency
		total_payable_interest: DF.Currency
		zip_code: DF.Int
	# end: auto-generated types

	def validate(self):
		self.set_pledge_amount()
		self.set_loan_amount()
		self.validate_loan_amount()

		if self.is_term_loan:
			self.validate_repayment_method()

		self.validate_loan_product()
		self.validate_employee()

		self.get_repayment_details()
		self.check_sanctioned_amount_limit()

	def before_save(self):
		if self.applicant_type == "Customer":
			if not self.applicant:
				customer = frappe.new_doc("Customer")
				customer.customer_name = self.first_name or "" + " " + self.last_name or ""
				customer.type = "Company"
				customer.mobile_number = self.applicant_phone_number
				customer.email_address = self.applicant_email_address
				# need to save customer first to link back from contact and address
				customer.save()

				# copying over contact details into the contact doctype
				contact = frappe.new_doc("Contact")
				contact.first_name = self.first_name
				contact.last_name = self.last_name
				contact.append("email_ids", {"email_id": self.applicant_email_address, "is_primary": True})
				contact.append(
					"phone_nos", {"phone": self.applicant_phone_number, "is_primary_mobile_no": True}
				)

				# link back to customer
				contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})
				contact.save()

				address = frappe.new_doc("Address")
				address.address_type = "Billing"

				# two different naming conventions = chaos
				if any(
					[self.address_line_1, self.address_line_2, self.city, self.state, self.zip_code]
				):  # address should be optional
					address.address_line1 = self.address_line_1
					address.address_line2 = self.address_line_2
					address.city = self.city
					address.state = self.state
					address.country = self.country
					address.pincode = self.zip_code
					address.append("links", {"link_doctype": "Customer", "link_name": customer.name})

					address.save()

					customer.customer_primary_address = address.name

				customer.customer_primary_contact = contact.name

				customer.save()

				self.applicant = customer.name

	def validate_repayment_method(self):
		if self.repayment_method == "Repay Over Number of Periods" and not self.repayment_periods:
			frappe.throw(_("Please enter Repayment Periods"))

		if self.repayment_method == "Repay Fixed Amount per Period":
			if not self.repayment_amount:
				frappe.throw(_("Please enter repayment Amount"))
			if self.repayment_amount > self.loan_amount:
				frappe.throw(_("Monthly Repayment Amount cannot be greater than Loan Amount"))

	def validate_loan_product(self):
		company = frappe.get_value("Loan Product", self.loan_product, "company")
		if company != self.company:
			frappe.throw(_("Please select Loan Product for company {0}").format(frappe.bold(self.company)))

	def validate_employee(self):
		if self.applicant_type == "Employee":
			employee_company = frappe.get_value("Employee", self.applicant, "company")
			if employee_company != self.company:
				frappe.throw(
					_("Selected employee belongs to {0}. Please select an employee from company {1}.").format(
						frappe.bold(employee_company), frappe.bold(self.company)
					)
				)

	def validate_loan_amount(self):
		if not self.loan_amount:
			frappe.throw(_("Loan Amount is mandatory"))

		maximum_loan_limit = frappe.db.get_value(
			"Loan Product", self.loan_product, "maximum_loan_amount"
		)
		if maximum_loan_limit and self.loan_amount > maximum_loan_limit:
			frappe.throw(
				_("Loan Amount cannot exceed Maximum Loan Amount of {0}").format(maximum_loan_limit)
			)

		if self.maximum_loan_amount and self.loan_amount > self.maximum_loan_amount:
			frappe.throw(
				_("Loan Amount exceeds maximum loan amount of {0} as per proposed securities").format(
					self.maximum_loan_amount
				)
			)

	def check_sanctioned_amount_limit(self):
		sanctioned_amount_limit = get_sanctioned_amount_limit(
			self.applicant_type, self.applicant, self.company
		)

		if sanctioned_amount_limit:
			total_loan_amount = get_total_loan_amount(self.applicant_type, self.applicant, self.company)

		if sanctioned_amount_limit and flt(self.loan_amount) + flt(total_loan_amount) > flt(
			sanctioned_amount_limit
		):
			frappe.throw(
				_("Sanctioned Amount limit crossed for {0} {1}").format(
					self.applicant_type, frappe.bold(self.applicant)
				)
			)

	def set_pledge_amount(self):
		for proposed_pledge in self.proposed_pledges:

			if not proposed_pledge.qty:
				frappe.throw(_("Qty is mandatory for loan security!"))

			if not proposed_pledge.loan_security_price:
				loan_security_price = get_loan_security_price(proposed_pledge.loan_security)

				if loan_security_price:
					proposed_pledge.loan_security_price = loan_security_price
				else:
					frappe.throw(
						_("No valid Loan Security Price found for {0}").format(
							frappe.bold(proposed_pledge.loan_security)
						)
					)

			proposed_pledge.amount = proposed_pledge.qty * proposed_pledge.loan_security_price
			proposed_pledge.post_haircut_amount = cint(
				proposed_pledge.amount - (proposed_pledge.amount * proposed_pledge.haircut / 100)
			)

	def get_repayment_details(self):

		if self.is_term_loan:
			if self.repayment_method == "Repay Over Number of Periods":
				self.repayment_amount = get_monthly_repayment_amount(
					self.loan_amount, self.rate_of_interest, self.repayment_periods, "Monthly"
				)

			if self.repayment_method == "Repay Fixed Amount per Period":
				monthly_interest_rate = flt(self.rate_of_interest) / (12 * 100)
				if monthly_interest_rate:
					min_repayment_amount = self.loan_amount * monthly_interest_rate
					if self.repayment_amount - min_repayment_amount <= 0:
						frappe.throw(_("Repayment Amount must be greater than " + str(flt(min_repayment_amount, 2))))
					self.repayment_periods = math.ceil(
						(math.log(self.repayment_amount) - math.log(self.repayment_amount - min_repayment_amount))
						/ (math.log(1 + monthly_interest_rate))
					)
				else:
					self.repayment_periods = self.loan_amount / self.repayment_amount

			self.calculate_payable_amount()
		else:
			self.total_payable_amount = self.loan_amount

	def calculate_payable_amount(self):
		balance_amount = self.loan_amount
		self.total_payable_amount = 0
		self.total_payable_interest = 0

		while balance_amount > 0:
			interest_amount = rounded(balance_amount * flt(self.rate_of_interest) / (12 * 100))
			balance_amount = rounded(balance_amount + interest_amount - self.repayment_amount)

			self.total_payable_interest += interest_amount

		self.total_payable_amount = self.loan_amount + self.total_payable_interest

	def set_loan_amount(self):
		if self.is_secured_loan and not self.proposed_pledges:
			frappe.throw(_("Proposed Pledges are mandatory for secured Loans"))

		if self.is_secured_loan and self.proposed_pledges:
			self.maximum_loan_amount = 0
			for security in self.proposed_pledges:
				self.maximum_loan_amount += flt(security.post_haircut_amount)

		if not self.loan_amount and self.is_secured_loan and self.proposed_pledges:
			self.loan_amount = self.maximum_loan_amount


@frappe.whitelist()
def create_loan(source_name, target_doc=None, submit=0):
	def update_accounts(source_doc, target_doc, source_parent):
		account_details = frappe.get_all(
			"Loan Product",
			fields=[
				"payment_account",
				"loan_account",
				"interest_income_account",
				"penalty_income_account",
			],
			filters={"name": source_doc.loan_product},
		)[0]

		if source_doc.is_secured_loan:
			target_doc.maximum_loan_amount = 0

		target_doc.payment_account = account_details.payment_account
		target_doc.loan_account = account_details.loan_account
		target_doc.interest_income_account = account_details.interest_income_account
		target_doc.penalty_income_account = account_details.penalty_income_account
		target_doc.loan_application = source_name

	doclist = get_mapped_doc(
		"Loan Application",
		source_name,
		{
			"Loan Application": {
				"doctype": "Loan",
				"validation": {"docstatus": ["=", 1]},
				"postprocess": update_accounts,
			}
		},
		target_doc,
	)

	if submit:
		doclist.submit()

	return doclist


@frappe.whitelist()
def create_loan_security_assignment(loan_application, loan=None):
	loan_application_doc = frappe.get_doc("Loan Application", loan_application)

	lsa = frappe.new_doc("Loan Security Assignment")
	lsa.applicant_type = loan_application_doc.applicant_type
	lsa.applicant = loan_application_doc.applicant
	lsa.company = loan_application_doc.company
	lsa.loan_application = loan_application
	lsa.loan = loan

	for pledge in loan_application_doc.proposed_pledges:
		lsa.append(
			"securities",
			{
				"loan_security": pledge.loan_security,
				"qty": pledge.qty,
				"loan_security_price": pledge.loan_security_price,
				"haircut": pledge.haircut,
			},
		)

	lsa.save()
	lsa.submit()

	message = _("Loan Security Assignment Created : {0}").format(lsa.name)
	frappe.msgprint(message)

	return lsa.name


# This is a sandbox method to get the proposed pledges
@frappe.whitelist()
def get_proposed_pledge(securities):
	if isinstance(securities, str):
		securities = json.loads(securities)

	proposed_pledges = {"securities": []}
	maximum_loan_amount = 0

	for security in securities:
		security = frappe._dict(security)
		if not security.qty and not security.amount:
			frappe.throw(_("Qty or Amount is mandatroy for loan security"))

		security.loan_security_price = get_loan_security_price(security.loan_security)

		if not security.qty:
			security.qty = cint(security.amount / security.loan_security_price)

		security.amount = security.qty * security.loan_security_price
		security.post_haircut_amount = cint(security.amount - (security.amount * security.haircut / 100))

		maximum_loan_amount += security.post_haircut_amount

		proposed_pledges["securities"].append(security)

	proposed_pledges["maximum_loan_amount"] = maximum_loan_amount

	return proposed_pledges


@frappe.whitelist()
def check_duplicate_customers(applicant_phone_number=None, applicant_email_address=None):
	# check if there are customer entries with the same email and/or phone
	customer_doc = frappe.qb.DocType("Customer")

	# matching any one condition will suffice
	conditions = []

	if applicant_phone_number:
		conditions.append((applicant_phone_number == customer_doc.mobile_no))

	if applicant_email_address:
		conditions.append(applicant_email_address == customer_doc.email_id)

	if conditions:
		query = frappe.qb.from_(customer_doc).where(Criterion.any(conditions)).select(customer_doc.name)
		duplicates = [i[0] for i in query.run(as_list=True)]
		return duplicates
	return []
