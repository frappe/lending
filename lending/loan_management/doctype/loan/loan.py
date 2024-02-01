# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import (
	add_days,
	add_months,
	cint,
	date_diff,
	flt,
	get_last_day,
	getdate,
	now_datetime,
	nowdate,
)

import erpnext
from erpnext.accounts.doctype.journal_entry.journal_entry import get_payment_entry
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_limit_change_log.loan_limit_change_log import (
	create_loan_limit_change_log,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)


class Loan(AccountsController):
	def validate(self):
		self.set_loan_amount()
		self.validate_loan_amount()
		self.set_missing_fields()
		self.validate_cost_center()
		self.validate_accounts()
		self.check_sanctioned_amount_limit()
		self.set_cyclic_date()
		self.set_default_charge_account()
		self.set_available_limit_amount()
		self.validate_repayment_terms()

		if not self.is_term_loan or (self.is_term_loan and not self.is_new()):
			self.calculate_totals()

	def validate_accounts(self):
		for fieldname in [
			"payment_account",
			"loan_account",
			"interest_income_account",
			"penalty_income_account",
		]:
			company = frappe.get_value("Account", self.get(fieldname), "company")

			if company != self.company:
				frappe.throw(
					_("Account {0} does not belongs to company {1}").format(
						frappe.bold(self.get(fieldname)), frappe.bold(self.company)
					)
				)

	def validate_cost_center(self):
		if not self.cost_center and self.rate_of_interest != 0.0:
			self.cost_center = frappe.db.get_value("Company", self.company, "cost_center")

			if not self.cost_center:
				frappe.throw(_("Cost center is mandatory for loans having rate of interest greater than 0"))

	def set_cyclic_date(self):
		if (
			self.repayment_schedule_type == "Monthly as per cycle date"
			and self.repayment_frequency == "Monthly"
		):
			cyclic_date = get_cyclic_date(self.loan_product, self.posting_date)
			self.repayment_start_date = cyclic_date

			if self.moratorium_tenure:
				self.repayment_start_date = add_months(self.repayment_start_date, self.moratorium_tenure)

	def set_default_charge_account(self):
		for charge in self.get("loan_charges"):
			if not charge.account:
				account = frappe.get_cached_value(
					"Loan Charges", {"parent": self.loan_product, "charge_type": charge.charge}, "income_account"
				)

				if not account:
					account = frappe.get_cached_value(
						"Item Default", {"parent": charge.charge, "company": self.company}, "income_account"
					)

				charge.account = account

	def set_available_limit_amount(self):
		self.available_limit_amount = self.maximum_limit_amount

	def validate_repayment_terms(self):
		if self.is_term_loan and self.repayment_schedule_type != "Line of Credit":
			if not self.repayment_periods:
				frappe.throw(_("Repayment periods is mandatory for term loans"))

	def on_submit(self):
		self.link_loan_security_assignment()
		# Interest accrual for backdated term loans
		self.accrue_loan_interest()
		self.create_loan_limit_change_log("Loan Booking", self.posting_date)

	def on_cancel(self):
		self.unlink_loan_security_assignment()
		self.cancel_and_delete_repayment_schedule()
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]

	def on_update_after_submit(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import reverse_demands
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)

		if self.watch_period_end_date and getdate() < getdate(self.watch_period_end_date):
			frappe.throw(_("Cannot un mark as NPA before watch period end date"))

		update_manual_npa_check(self.manual_npa, self.applicant_type, self.applicant, self.posting_date)
		move_unpaid_interest_to_suspense_ledger(
			applicant_type=self.applicant_type, applicant=self.applicant, reverse=not self.manual_npa
		)

		if self.has_value_changed("freeze_account") and self.freeze_account:
			create_loan_feeze_log(self.name, self.freeze_date, self.freeze_reason)
			reverse_demands(self.name, self.freeze_date)
			reverse_loan_interest_accruals(self.name, self.freeze_date)

		self.create_loan_limit_change_log("Limit Renewal", nowdate())

	def create_loan_limit_change_log(self, event, date):
		doc_before_save = self.get_doc_before_save()

		if self.repayment_schedule_type == "Line of Credit":
			create_loan_limit_change_log(
				loan=self.name,
				event=event,
				change_date=date,
				value_type="Maximum Limit Amount",
				value_change=self.maximum_limit_amount
				if event == "Loan Booking"
				else self.maximum_limit_amount - doc_before_save.maximum_limit_amount,
			)

	def before_update_after_submit(self):
		self.update_available_limit_amount()

	def update_available_limit_amount(self):
		if self.maximum_limit_amount < self.utilized_limit_amount:
			frappe.throw(_("New maximum limit amount cannot be lesser than the utilized limit amount"))

		self.available_limit_amount += self.maximum_limit_amount - frappe.db.get_value(
			"Loan", self.name, "maximum_limit_amount"
		)

	def set_missing_fields(self):
		if not self.company:
			self.company = erpnext.get_default_company()

		if not self.posting_date:
			self.posting_date = nowdate()

		if self.loan_product and not self.rate_of_interest:
			self.rate_of_interest = frappe.db.get_value(
				"Loan Product", self.loan_product, "rate_of_interest"
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

	def submit_draft_schedule(self):
		draft_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": self.name, "docstatus": 0}, "name"
		)
		if draft_schedule:
			schedule = frappe.get_doc("Loan Repayment Schedule", draft_schedule)
			schedule.submit()

	def cancel_and_delete_repayment_schedule(self):
		schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": self.name, "docstatus": 1}, "name"
		)
		if schedule:
			schedule = frappe.get_doc("Loan Repayment Schedule", schedule)
			schedule.cancel()

	def calculate_totals(self, on_insert=False):
		self.total_payment = 0
		self.total_interest_payable = 0
		self.total_amount_paid = 0

		if not self.is_term_loan:
			self.total_payment = self.loan_amount

		if on_insert:
			self.db_set("total_interest_payable", self.total_interest_payable)
			self.db_set("monthly_repayment_amount", self.monthly_repayment_amount)
			self.db_set("total_payment", self.total_payment)

	def set_loan_amount(self):
		if self.repayment_schedule_type == "Line of Credit":
			self.loan_amount = self.maximum_limit_amount

		if self.loan_application and not self.loan_amount:
			self.loan_amount = frappe.db.get_value("Loan Application", self.loan_application, "loan_amount")

	def validate_loan_amount(self):
		if self.maximum_limit_amount and self.loan_amount > self.maximum_limit_amount:
			msg = _("Loan amount cannot be greater than {0}").format(self.maximum_limit_amount)
			frappe.throw(msg)

		if not self.loan_amount:
			frappe.throw(_("Loan amount is mandatory"))

	def link_loan_security_assignment(self):
		if self.is_secured_loan and self.loan_application:
			lsa = frappe.qb.DocType("Loan Security Assignment")
			lsalad = frappe.qb.DocType("Loan Security Assignment Loan Application Detail")

			lsa_and_maximum_loan_value = (
				frappe.qb.from_(lsa)
				.inner_join(lsalad)
				.on(lsalad.parent == lsa.name)
				.select(lsa.name, Sum(lsa.maximum_loan_value))
				.where(lsa.status == "Pledge Requested")
				.where(lsalad.loan_application == self.loan_application)
			).run()

			if lsa_and_maximum_loan_value:
				lsa = frappe.get_doc("Loan Security Assignment", lsa_and_maximum_loan_value[0][0])
				lsa.append(
					"allocated_loans",
					{
						"loan": self.name,
					},
				)
				lsa.pledge_time = now_datetime()
				lsa.status = "Pledged"
				lsa.save()

				self.db_set("maximum_loan_amount", lsa_and_maximum_loan_value[0][1])

	def accrue_loan_interest(self):
		from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
			process_loan_interest_accrual_for_loans,
		)

		if getdate(self.repayment_start_date) < getdate() and self.is_term_loan:
			process_loan_interest_accrual_for_loans(
				posting_date=getdate(), loan_product=self.loan_product, loan=self.name
			)

	def unlink_loan_security_assignment(self):
		pledges = frappe.get_all(
			"Loan Security Assignment", fields=["name"], filters={"loan": self.name}
		)
		pledge_list = [d.name for d in pledges]
		if pledge_list:
			frappe.db.sql(
				"""UPDATE `tabLoan Security Assignment` SET
				loan = '', status = 'Unpledged'
				where name in (%s) """
				% (", ".join(["%s"] * len(pledge_list))),
				tuple(pledge_list),
			)  # nosec


def update_total_amount_paid(doc):
	total_amount_paid = 0
	for data in doc.repayment_schedule:
		if data.paid:
			total_amount_paid += data.total_payment
	frappe.db.set_value("Loan", doc.name, "total_amount_paid", total_amount_paid)


def get_total_loan_amount(applicant_type, applicant, company):
	pending_amount = 0
	loan_details = frappe.db.get_all(
		"Loan",
		filters={
			"applicant_type": applicant_type,
			"company": company,
			"applicant": applicant,
			"docstatus": 1,
			"status": ("!=", "Closed"),
		},
		fields=[
			"status",
			"total_payment",
			"disbursed_amount",
			"total_interest_payable",
			"total_principal_paid",
			"written_off_amount",
		],
	)

	interest_amount = flt(
		frappe.db.get_value(
			"Loan Interest Accrual",
			{"applicant_type": applicant_type, "company": company, "applicant": applicant, "docstatus": 1},
			"sum(interest_amount - paid_interest_amount)",
		)
	)

	for loan in loan_details:
		if loan.status in ("Disbursed", "Loan Closure Requested"):
			pending_amount += (
				flt(loan.total_payment)
				- flt(loan.total_interest_payable)
				- flt(loan.total_principal_paid)
				- flt(loan.written_off_amount)
			)
		elif loan.status == "Partially Disbursed":
			pending_amount += (
				flt(loan.disbursed_amount)
				- flt(loan.total_interest_payable)
				- flt(loan.total_principal_paid)
				- flt(loan.written_off_amount)
			)
		elif loan.status == "Sanctioned":
			pending_amount += flt(loan.total_payment)

	pending_amount += interest_amount

	return pending_amount


def get_sanctioned_amount_limit(applicant_type, applicant, company):
	return frappe.db.get_value(
		"Sanctioned Loan Amount",
		{"applicant_type": applicant_type, "company": company, "applicant": applicant},
		"sanctioned_amount_limit",
	)


@frappe.whitelist()
def request_loan_closure(loan, posting_date=None):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	if not posting_date:
		posting_date = getdate()

	amounts = calculate_amounts(loan, posting_date)
	pending_amount = (
		amounts["pending_principal_amount"]
		+ amounts["unaccrued_interest"]
		+ amounts["interest_amount"]
		+ amounts["penalty_amount"]
	)

	loan_product = frappe.get_value("Loan", loan, "loan_product")
	write_off_limit = frappe.get_value("Loan Product", loan_product, "write_off_amount")

	if pending_amount and abs(pending_amount) < write_off_limit:
		# Auto create loan write off and update status as loan closure requested
		write_off = make_loan_write_off(loan)
		write_off.submit()
	elif pending_amount > 0:
		frappe.throw(_("Cannot close loan as there is an outstanding of {0}").format(pending_amount))

	frappe.db.set_value("Loan", loan, "status", "Loan Closure Requested")


@frappe.whitelist()
def get_loan_application(loan_application):
	loan = frappe.get_doc("Loan Application", loan_application)
	if loan:
		return loan.as_dict()


@frappe.whitelist()
def close_unsecured_term_loan(loan):
	loan_details = frappe.db.get_value(
		"Loan", {"name": loan}, ["status", "is_term_loan", "is_secured_loan"], as_dict=1
	)

	if (
		loan_details.status == "Loan Closure Requested"
		and loan_details.is_term_loan
		and not loan_details.is_secured_loan
	):
		frappe.db.set_value("Loan", loan, "status", "Closed")
	else:
		frappe.throw(_("Cannot close this loan until full repayment"))


@frappe.whitelist()
def make_loan_disbursement(
	loan,
	disbursement_amount=0,
	as_dict=0,
	submit=0,
	repayment_start_date=None,
	repayment_frequency=None,
	posting_date=None,
	disbursement_date=None,
	bank_account=None,
	is_term_loan=None,
):
	loan_doc = frappe.get_doc("Loan", loan)
	disbursement_entry = frappe.new_doc("Loan Disbursement")
	disbursement_entry.against_loan = loan_doc.name
	disbursement_entry.applicant_type = loan_doc.applicant_type
	disbursement_entry.applicant = loan_doc.applicant
	disbursement_entry.company = loan_doc.company
	disbursement_entry.disbursement_date = posting_date or nowdate()
	disbursement_entry.posting_date = disbursement_date or nowdate()
	disbursement_entry.bank_account = bank_account
	disbursement_entry.repayment_start_date = repayment_start_date
	disbursement_entry.repayment_frequency = repayment_frequency
	disbursement_entry.disbursed_amount = disbursement_amount
	disbursement_entry.is_term_loan = is_term_loan
	disbursement_entry.repayment_schedule_type = loan_doc.repayment_schedule_type

	for charge in loan_doc.get("loan_charges"):
		disbursement_entry.append(
			"loan_disbursement_charges",
			{"charge": charge.charge, "amount": charge.amount, "account": charge.account},
		)

	if submit:
		disbursement_entry.submit()

	if as_dict:
		return disbursement_entry.as_dict()
	else:
		return disbursement_entry


@frappe.whitelist()
def make_repayment_entry(loan, applicant_type, applicant, loan_product, company, as_dict=0):
	repayment_entry = frappe.new_doc("Loan Repayment")
	repayment_entry.against_loan = loan
	repayment_entry.applicant_type = applicant_type
	repayment_entry.applicant = applicant
	repayment_entry.company = company
	repayment_entry.loan_product = loan_product
	repayment_entry.posting_date = nowdate()

	if as_dict:
		return repayment_entry.as_dict()
	else:
		return repayment_entry


@frappe.whitelist()
def make_loan_write_off(loan, company=None, posting_date=None, amount=0, as_dict=0):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	if not company:
		company = frappe.get_value("Loan", loan, "company")

	if not posting_date:
		posting_date = getdate()

	amounts = calculate_amounts(loan, posting_date)
	pending_amount = amounts["pending_principal_amount"]

	if amount and (amount > pending_amount):
		frappe.throw(_("Write Off amount cannot be greater than pending loan amount"))

	if not amount:
		amount = pending_amount

	# get default write off account from company master
	write_off_account = frappe.get_value("Company", company, "write_off_account")

	write_off = frappe.new_doc("Loan Write Off")
	write_off.loan = loan
	write_off.posting_date = posting_date
	write_off.write_off_account = write_off_account
	write_off.write_off_amount = amount
	write_off.save()

	if as_dict:
		return write_off.as_dict()
	else:
		return write_off


@frappe.whitelist()
def unpledge_security(
	loan=None,
	loan_security_assignment=None,
	security_map=None,
	as_dict=0,
	save=0,
	submit=0,
	approve=0,
):
	# if no security_map is passed it will be considered as full unpledge
	if security_map and isinstance(security_map, str):
		security_map = json.loads(security_map)

	if loan:
		pledge_qty_map = security_map or get_pledged_security_qty(loan)
		loan_doc = frappe.get_doc("Loan", loan)
		unpledge_request = create_loan_security_release(
			pledge_qty_map, loan_doc.name, loan_doc.company, loan_doc.applicant_type, loan_doc.applicant
		)
	# will unpledge qty based on Loan Security Assignment
	elif loan_security_assignment:
		security_map = {}
		pledge_doc = frappe.get_doc("Loan Security Assignment", loan_security_assignment)
		for security in pledge_doc.securities:
			security_map.setdefault(security.loan_security, security.qty)

		unpledge_request = create_loan_security_release(
			security_map,
			pledge_doc.loan,
			pledge_doc.company,
			pledge_doc.applicant_type,
			pledge_doc.applicant,
		)

	if save:
		unpledge_request.save()

	if submit:
		unpledge_request.submit()

	if approve:
		if unpledge_request.docstatus == 1:
			unpledge_request.status = "Approved"
			unpledge_request.save()
		else:
			frappe.throw(_("Only submitted unpledge requests can be approved"))

	if as_dict:
		return unpledge_request
	else:
		return unpledge_request


def create_loan_security_release(unpledge_map, loan, company, applicant_type, applicant):
	unpledge_request = frappe.new_doc("Loan Security Release")
	unpledge_request.applicant_type = applicant_type
	unpledge_request.applicant = applicant
	unpledge_request.loan = loan
	unpledge_request.company = company

	for security, qty in unpledge_map.items():
		if qty:
			unpledge_request.append("securities", {"loan_security": security, "qty": qty})

	return unpledge_request


@frappe.whitelist()
def get_shortfall_applicants():
	loans = frappe.get_all("Loan Security Shortfall", {"status": "Pending"}, pluck="loan")
	applicants = set(frappe.get_all("Loan", {"name": ("in", loans)}, pluck="name"))

	return {"value": len(applicants), "fieldtype": "Int"}


@frappe.whitelist()
def make_refund_jv(loan, amount=0, reference_number=None, reference_date=None, submit=0):
	loan_details = frappe.db.get_value(
		"Loan",
		loan,
		[
			"applicant_type",
			"applicant",
			"loan_account",
			"payment_account",
			"posting_date",
			"company",
			"name",
			"total_payment",
			"total_principal_paid",
		],
		as_dict=1,
	)

	loan_details.doctype = "Loan"
	loan_details[loan_details.applicant_type.lower()] = loan_details.applicant

	if not amount:
		amount = flt(loan_details.total_principal_paid - loan_details.total_payment)

		if amount < 0:
			frappe.throw(_("No excess amount pending for refund"))

	refund_jv = get_payment_entry(
		loan_details,
		{
			"party_type": loan_details.applicant_type,
			"party_account": loan_details.loan_account,
			"amount_field_party": "debit_in_account_currency",
			"amount_field_bank": "credit_in_account_currency",
			"amount": amount,
			"bank_account": loan_details.payment_account,
		},
	)

	if reference_number:
		refund_jv.cheque_no = reference_number

	if reference_date:
		refund_jv.cheque_date = reference_date

	if submit:
		refund_jv.submit()

	return refund_jv


@frappe.whitelist()
def update_days_past_due_in_loans(
	posting_date=None, loan_product=None, loan_name=None, process_loan_classification=None
):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_unpaid_demands

	"""Update days past due in loans"""
	posting_date = posting_date or getdate()

	demands = get_unpaid_demands(loan_name, posting_date=posting_date, loan_product=loan_product)
	threshold_map = get_dpd_threshold_map()
	checked_loans = []

	applicant_type = frappe.db.get_value("Loan", loan_name, "applicant_type")
	applicant = frappe.db.get_value("Loan", loan_name, "applicant")

	for loan in demands:
		is_npa = 0
		days_past_due = date_diff(getdate(posting_date), getdate(loan.demand_date))
		if days_past_due < 0:
			days_past_due = 0

		threshold = threshold_map.get(loan.loan_product, 0)

		if days_past_due and threshold and days_past_due > threshold:
			is_npa = 1

		update_loan_and_customer_status(
			loan.loan,
			loan.company,
			applicant_type,
			applicant,
			days_past_due,
			is_npa,
			posting_date or getdate(),
		)

		create_dpd_record(loan.loan, posting_date, days_past_due, process_loan_classification)
		checked_loans.append(loan.loan)

	open_loans_with_no_overdue = []
	if loan_name and not demands:
		open_loans_with_no_overdue = [
			frappe.db.get_value(
				"Loan", loan_name, ["name", "company", "applicant_type", "applicant"], as_dict=1
			)
		]
	elif not loan_name:
		open_loans_with_no_overdue = frappe.db.get_all(
			"Loan",
			{"status": "Disbursed", "docstatus": 1, "name": ("not in", checked_loans)},
			["name", "company", "applicant_type", "applicant"],
		)

	for d in open_loans_with_no_overdue:
		update_loan_and_customer_status(
			d.name, d.company, d.applicant_type, d.applicant, 0, 0, posting_date or getdate()
		)

		create_dpd_record(d.name, posting_date, 0, process_loan_classification)


def restore_pervious_dpd_state(applicant_type, applicant, repayment_reference):
	pac = frappe.db.get_value(
		"Process Loan Classification",
		{"payment_reference": repayment_reference},
		"previous_process",
	)
	for d in frappe.db.get_all(
		"Days Past Due Log",
		filters={
			"process_loan_classification": pac,
			"applicant_type": applicant_type,
			"applicant": applicant,
		},
		fields=["loan", "days_past_due"],
	):
		frappe.db.set_value("Loan", d.loan, "days_past_due", d.days_past_due)


def create_dpd_record(loan, posting_date, days_past_due, process_loan_classification=None):
	frappe.get_doc(
		{
			"doctype": "Days Past Due Log",
			"loan": loan,
			"posting_date": posting_date,
			"days_past_due": days_past_due,
			"process_loan_classification": process_loan_classification,
		}
	).insert(ignore_permissions=True)


def update_loan_and_customer_status(
	loan, company, applicant_type, applicant, days_past_due, is_npa, posting_date
):
	classification_code, classification_name = get_classification_code_and_name(
		days_past_due, company
	)

	frappe.db.set_value(
		"Loan",
		loan,
		{
			"days_past_due": days_past_due,
			"classification_code": classification_code,
			"classification_name": classification_name,
		},
	)

	if is_npa:
		for loan in frappe.get_all(
			"Loan",
			{
				"status": ("in", ["Disbursed", "Partially Disbursed"]),
				"applicant_type": applicant_type,
				"applicant": applicant,
			},
			pluck="name",
		):
			move_unpaid_interest_to_suspense_ledger(
				loan, posting_date, applicant_type=applicant_type, applicant=applicant
			)

		update_all_linked_loan_customer_npa_status(
			is_npa, is_npa, applicant_type, applicant, posting_date
		)
	else:
		max_dpd = frappe.db.get_value(
			"Loan", {"applicant_type": applicant_type, "applicant": applicant}, ["MAX(days_past_due)"]
		)

		""" if max_dpd is greater than 0 loan still NPA, do nothing"""
		if max_dpd == 0:
			update_all_linked_loan_customer_npa_status(
				is_npa, is_npa, applicant_type, applicant, posting_date
			)


def update_all_linked_loan_customer_npa_status(
	is_npa, manual_npa, applicant_type, applicant, posting_date
):
	"""Update NPA status of all linked customers"""
	update_system_npa_check(is_npa, applicant_type, applicant, posting_date)
	update_manual_npa_check(manual_npa, applicant_type, applicant, posting_date)


def update_system_npa_check(is_npa, applicant_type, applicant, posting_date):
	_loan = frappe.qb.DocType("Loan")
	frappe.qb.update(_loan).set(_loan.is_npa, is_npa).where(
		(_loan.docstatus == 1)
		& (_loan.status.isin(["Disbursed", "Partially Disbursed"]))
		& (_loan.applicant_type == applicant_type)
		& (_loan.applicant == applicant)
		& (_loan.watch_period_end_date.isnull() | _loan.watch_period_end_date < posting_date)
	).run()

	frappe.db.set_value("Customer", applicant, "is_npa", is_npa)


def update_manual_npa_check(manual_npa, applicant_type, applicant, posting_date):
	_loan = frappe.qb.DocType("Loan")
	frappe.qb.update(_loan).set(_loan.manual_npa, manual_npa).where(
		(_loan.docstatus == 1)
		& (_loan.status.isin(["Disbursed", "Partially Disbursed"]))
		& (_loan.applicant_type == applicant_type)
		& (_loan.applicant == applicant)
		& (_loan.watch_period_end_date.isnull() | _loan.watch_period_end_date < posting_date)
	).run()

	frappe.db.set_value("Customer", applicant, "is_npa", manual_npa)


def update_watch_period_date_for_all_loans(watch_period_end_date, applicant_type, applicant):
	_loan = frappe.qb.DocType("Loan")
	frappe.qb.update(_loan).set(_loan.watch_period_end_date, watch_period_end_date).where(
		(_loan.docstatus == 1)
		& (_loan.status.isin(["Disbursed", "Partially Disbursed"]))
		& (_loan.applicant_type == applicant_type)
		& (_loan.applicant == applicant)
	).run()


def get_classification_code_and_name(days_past_due, company):
	classification_code = ""
	classification_name = ""

	ranges = frappe.get_all(
		"Loan Classification Range",
		fields=[
			"min_dpd_range",
			"max_dpd_range",
			"classification_code",
			"classification_name",
		],
		filters={"parent": company},
		order_by="min_dpd_range",
	)

	for range in ranges:
		if range.min_dpd_range <= days_past_due <= range.max_dpd_range:
			return range.classification_code, range.classification_name

	return classification_code, classification_name


def get_dpd_threshold_map():
	return frappe._dict(
		frappe.get_all("Loan Product", fields=["name", "days_past_due_threshold_for_npa"], as_list=1)
	)


def move_unpaid_interest_to_suspense_ledger(
	loan=None, posting_date=None, applicant_type=None, applicant=None, reverse=0
):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_unpaid_demands

	posting_date = posting_date or getdate()
	previous_npa = frappe.db.get_value("Loan", loan, "is_npa")
	if previous_npa:
		return

	unpaid_demands = get_unpaid_demands(loan, posting_date=posting_date)

	for demand in unpaid_demands:
		amount = demand.demand_amount

		if reverse:
			amount = -1 * amount

		loan_product = frappe.db.get_value("Loan", loan, "loan_product")

		account_details = frappe.get_value(
			"Loan Product",
			loan_product,
			[
				"suspense_interest_receivable",
				"suspense_interest_income",
				"interest_receivable_account",
				"interest_income_account",
			],
			as_dict=1,
		)
		jv = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"posting_date": posting_date,
				"company": demand.company,
				"accounts": [
					{
						"account": account_details.suspense_interest_receivable,
						"party": applicant,
						"party_type": applicant_type,
						"debit_in_account_currency": amount,
						"debit": amount,
						"reference_type": "Loan",
						"reference_name": loan,
						"cost_center": erpnext.get_default_cost_center(demand.company),
					},
					{
						"account": account_details.interest_receivable_account,
						"party": applicant,
						"party_type": applicant_type,
						"credit_in_account_currency": amount,
						"credit": amount,
						"reference_type": "Loan",
						"reference_name": loan,
						"cost_center": erpnext.get_default_cost_center(demand.company),
					},
					{
						"account": account_details.suspense_interest_income,
						"credit_in_account_currency": amount,
						"credit": amount,
						"cost_center": erpnext.get_default_cost_center(demand.company),
					},
					{
						"account": account_details.interest_income_account,
						"debit": amount,
						"debit_in_account_currency": amount,
						"cost_center": erpnext.get_default_cost_center(demand.company),
					},
				],
			}
		)

		jv.submit()


@frappe.whitelist()
def get_cyclic_date(loan_product, posting_date):
	cycle_day, min_days_bw_disbursement_first_repayment = frappe.db.get_value(
		"Loan Product",
		loan_product,
		["cyclic_day_of_the_month", "min_days_bw_disbursement_first_repayment"],
	)
	cycle_day = cint(cycle_day)

	last_day_of_month = get_last_day(posting_date)
	cyclic_date = add_days(last_day_of_month, cycle_day)

	broken_period_days = date_diff(cyclic_date, posting_date)
	if broken_period_days < min_days_bw_disbursement_first_repayment:
		cyclic_date = add_days(get_last_day(cyclic_date), cycle_day)

	return cyclic_date


def create_loan_feeze_log(loan, freeze_date, reason):
	frappe.get_doc(
		{
			"doctype": "Loan Freeze Log",
			"loan": loan,
			"freeze_date": freeze_date,
			"reason_for_freezing": reason,
		}
	).insert(ignore_permissions=True)
