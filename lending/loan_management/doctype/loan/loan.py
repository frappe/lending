# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json
from datetime import date, timedelta

import frappe
from frappe import _
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
from frappe.utils.caching import redis_cache

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
		self.set_status()
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
			and not self.repayment_start_date
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
		if self.is_term_loan and self.repayment_schedule_type == "Repay Over Number of Periods":
			if not self.repayment_periods:
				frappe.throw(_("Repayment periods is mandatory for term loans"))

	def on_submit(self):
		self.link_loan_security_assignment()
		# Interest accrual for backdated term loans
		self.create_loan_limit_change_log("Loan Booking", self.posting_date)

	def on_cancel(self):
		# self.unlink_loan_security_assignment()
		self.cancel_and_delete_repayment_schedule()
		self.cancel_loan_security_assignment()
		self.ignore_linked_doctypes = [
			"GL Entry",
			"Payment Ledger Entry",
			"Sales Invoice",
			"Loan Interest Accrual",
			"Journal Entry",
			"Process Loan Interest Accrual",
			"Loan Transfer",
			"Loan Demand",
			"Loan Repayment",
			"Loan Adjustment",
			"Process Loan Classification",
			"Loan Restructure",
			"Process Loan Demand",
		]
		self.set_status()

	def set_status(self):
		if self.docstatus == 0:
			self.status = "Draft"
		elif self.docstatus == 1:
			self.db_set("status", "Sanctioned")
		elif self.docstatus == 2:
			self.db_set("status", "Cancelled")

	def on_update_after_submit(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import reverse_demands
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)
		from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
			process_loan_interest_accrual_for_loans,
		)

		if self.has_value_changed("unmark_npa") and self.unmark_npa:
			if self.watch_period_end_date and getdate() < getdate(self.watch_period_end_date):
				frappe.throw(_("Cannot un mark as NPA before watch period end date"))

		if self.has_value_changed("manual_npa"):
			update_all_linked_loan_customer_npa_status(
				self.manual_npa,
				self.applicant_type,
				self.applicant,
				nowdate(),
				loan=self.name,
				manual_npa=self.manual_npa,
				via_background_job=False,
			)
			if self.manual_npa:
				move_unpaid_interest_to_suspense_ledger(self.name)

		if self.has_value_changed("unmark_npa"):
			if self.unmark_npa:
				frappe.db.set_value("Loan", self.name, "is_npa", 0)

		if self.has_value_changed("freeze_account") and self.freeze_account:
			create_loan_feeze_log(self.name, self.freeze_date, self.get("freeze_reason"))
			reverse_demands(self.name, self.freeze_date)
			reverse_loan_interest_accruals(self.name, self.freeze_date)
			update_days_past_due_in_loans(posting_date=self.get("freeze_date"), loan_name=self.name)
			process_loan_interest_accrual_for_loans(posting_date=self.get("freeze_date"), loan=self.name)
		elif self.has_value_changed("freeze_account") and not self.freeze_account:
			self.db_set("freeze_date", None)
			process_loan_interest_accrual_for_loans(posting_date=nowdate(), loan=self.name)
			create_loan_feeze_log(self.name, None, self.get("freeze_reason"), unfreeze_date=nowdate())

		if self.has_value_changed("maximum_limit_amount"):
			self.db_set("loan_amount", self.maximum_limit_amount)

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
		schedules = frappe.db.get_all(
			"Loan Repayment Schedule", {"loan": self.name, "docstatus": 1}, pluck="name"
		)
		for schedule in schedules:
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
			lsa, maximum_loan_value = frappe.db.get_value(
				"Loan Security Assignment",
				{
					"loan_application": self.loan_application,
					"status": "Pledge Requested",
					"docstatus": 1,
				},
				["name", "maximum_loan_value"],
			)

			if lsa:
				frappe.db.set_value(
					"Loan Security Assignment",
					lsa,
					{
						"loan": self.name,
						"pledge_time": now_datetime(),
						"status": "Pledged",
					},
				)

				self.db_set("maximum_loan_amount", maximum_loan_value)

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

	def cancel_loan_security_assignment(self):
		if not self.loan_application:
			for assignment in frappe.get_all(
				"Loan Security Assignment",
				filters={"loan": self.name, "status": "Pledged"},
				fields=["name"],
			):
				doc = frappe.get_doc("Loan Security Assignment", assignment.name)
				doc.cancel()


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
		if loan.status in ("Disbursed", "Loan Closure Requested", "Active"):
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
def request_loan_closure(loan, posting_date=None, auto_close=0):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	if not posting_date:
		posting_date = getdate()

	amounts = calculate_amounts(loan, posting_date)
	pending_amount = (
		amounts["pending_principal_amount"]
		+ amounts["interest_amount"]
		+ amounts["penalty_amount"]
		+ amounts.get("excess_amount_paid", 0)
	)

	loan_product, loan_status = frappe.get_value("Loan", loan, ["loan_product", "status"])

	write_off_limit = frappe.get_value("Loan Product", loan_product, "write_off_amount")

	if pending_amount and abs(pending_amount) < write_off_limit or loan_status == "Settled":
		# Auto create loan write off and update status as loan closure requested
		write_off = make_loan_write_off(loan)
		write_off.submit()
	elif flt(pending_amount, precision) > 0:
		frappe.throw(_("Cannot close loan as there is an outstanding of {0}").format(pending_amount))

	if auto_close:
		status = "Closed"
		response = "Loan Closed Successfully"
	else:
		status = "Loan Closure Requested"
		response = "Loan Closure Requested Successfully"

	values = {
		"status": status,
	}
	if status == "Closed":
		schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan, "status": "Active", "docstatus": 1}
		)
		frappe.db.set_value("Loan Repayment Schedule", schedule, "status", "Closed")
		values["closure_date"] = posting_date

	frappe.db.set_value("Loan", loan, values)

	return {
		"message": response,
	}


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

	if loan_doc.repayment_schedule_type != "Line of Credit":
		disbursement_entry.repayment_method = loan_doc.repayment_method

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
	loan_name,
	posting_date=None,
	loan_product=None,
	process_loan_classification=None,
	ignore_freeze=False,
	is_backdated=0,
	via_background_job=False,
	force_update_dpd_in_loan=0,
):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_unpaid_demands

	"""Update days past due in loans"""
	posting_date = posting_date or getdate()

	if not loan_product:
		loan_product = frappe.get_value("Loan", loan_name, "loan_product")

	disbursements = frappe.db.get_all(
		"Loan Repayment Schedule",
		{"loan": loan_name, "status": ("in", ["Active", "Closed"]), "docstatus": 1},
		pluck="loan_disbursement",
	)

	for disbursement in disbursements:
		if getdate(posting_date) > add_days(getdate(), -1) or force_update_dpd_in_loan:
			demand = get_unpaid_demands(
				loan_name,
				posting_date=posting_date,
				loan_product=loan_product,
				demand_type="EMI",
				limit=1,
				loan_disbursement=disbursement,
			)
		else:
			if frappe.flags.in_test or frappe.flags.in_import:
				repost_days_past_due_log(
					loan_name,
					posting_date=posting_date,
					loan_product=loan_product,
					loan_disbursement=disbursement,
				)
			else:
				frappe.enqueue(
					repost_days_past_due_log,
					loan=loan_name,
					posting_date=posting_date,
					loan_product=loan_product,
					loan_disbursement=disbursement,
					queue="long",
					enqueue_after_commit=True,
				)

			return

		threshold_map = get_dpd_threshold_map()
		threshold_write_off_map = get_dpd_threshold_write_off_map()

		loan_details = frappe.db.get_value(
			"Loan", loan_name, ["applicant_type", "applicant", "freeze_date", "company"], as_dict=1
		)

		applicant_type = loan_details.get("applicant_type")
		applicant = loan_details.get("applicant")
		company = loan_details.get("company")
		freeze_date = loan_details.get("freeze_date")

		if not ignore_freeze and freeze_date and getdate(freeze_date) < getdate(posting_date):
			return

		if demand:
			demand = demand[0]
			is_npa = 0

			dpd_date = freeze_date or posting_date
			days_past_due = date_diff(getdate(dpd_date), getdate(demand.demand_date)) + 1
			if days_past_due < 0:
				days_past_due = 0

			threshold = threshold_map.get(demand.loan_product, 0)

			if days_past_due and threshold and days_past_due > threshold:
				is_npa = 1

			if freeze_date:
				days_past_due = 0
				is_npa = 0

			if posting_date == add_days(getdate(), -1) or force_update_dpd_in_loan:
				update_loan_and_customer_status(
					demand.loan,
					demand.company,
					applicant_type,
					applicant,
					days_past_due,
					is_npa,
					posting_date or getdate(),
					freeze_date=freeze_date,
					loan_disbursement=disbursement,
					is_backdated=is_backdated,
					dpd_threshold=threshold,
					via_background_job=via_background_job,
				)

			create_dpd_record(
				demand.loan, disbursement, posting_date, days_past_due, process_loan_classification
			)

			write_off_threshold = threshold_write_off_map.get(demand.company, 0)

			if write_off_threshold and days_past_due > write_off_threshold:
				create_loan_write_off(demand.loan, posting_date)
		else:
			# if no demand found, set DPD as 0
			threshold = threshold_map.get(loan_product, 0)

			update_loan_and_customer_status(
				loan_name,
				company,
				applicant_type,
				applicant,
				0,
				0,
				posting_date or getdate(),
				loan_disbursement=disbursement,
				is_backdated=is_backdated,
				dpd_threshold=threshold,
				via_background_job=via_background_job,
			)
			create_dpd_record(loan_name, disbursement, posting_date, 0, process_loan_classification)


def daterange(start_date: date, end_date: date):
	days = int((end_date - start_date).days)
	for n in range(days):
		yield start_date + timedelta(n)


def repost_days_past_due_log(loan, posting_date, loan_product, loan_disbursement):
	"""Get outstanding demands for a loan"""
	where_conditions = ""
	payment_conditions = ""

	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if loan_product:
		where_conditions += f"AND loan_product = '{loan_product}'"

	if loan_product == "Line of Credit":
		where_conditions += f"AND loan_disbursement = '{loan_disbursement}'"

	demands = frappe.db.sql(
		"""
		SELECT demand_date, loan_disbursement, demand_subtype, sum(demand_amount) as demand_amount, sum(outstanding_amount) as outstanding_amount
		FROM `tabLoan Demand`
		WHERE loan = %s
			AND docstatus = 1
			AND demand_type = "EMI"
			{0}
		GROUP BY demand_date, demand_subtype
		ORDER BY demand_date
	""".format(
			where_conditions
		),
		(loan),
		as_dict=1,
	)

	if demands:
		if loan_product:
			payment_conditions += f"AND loan_product = '{loan_product}'"

		if loan_product == "Line of Credit":
			payment_conditions += f"AND loan_disbursement = '{loan_disbursement}'"

		payment_against_demand = frappe.db.sql(
			"""
			SELECT posting_date, SUM(principal_amount_paid) as total_principal_paid, SUM(total_interest_paid) as total_interest_paid
			FROM `tabLoan Repayment`
			WHERE against_loan = %s
				and docstatus = 1
				{0}
			GROUP BY posting_date
			ORDER BY posting_date
		""".format(
				payment_conditions
			),
			(loan),
			as_dict=1,
		)

		for idx, payment in enumerate(payment_against_demand):
			next_payment_date = (
				payment_against_demand[idx + 1].posting_date
				if idx + 1 < len(payment_against_demand)
				else getdate()
			)
			for demand in demands:
				if demand.demand_date <= getdate(payment.posting_date):
					if demand.demand_subtype == "Interest" and flt(payment.total_interest_paid, precision) > 0:
						paid_interest = min(
							flt(payment.total_interest_paid, precision), flt(demand.demand_amount, precision)
						)
						demand.demand_amount -= paid_interest
						payment.total_interest_paid -= paid_interest

					if demand.demand_subtype == "Principal" and flt(payment.total_principal_paid, precision) > 0:
						paid_principal = min(
							flt(payment.total_principal_paid, precision), flt(demand.demand_amount, precision)
						)
						demand.demand_amount -= paid_principal
						payment.total_principal_paid -= paid_principal

			start_date = getdate(payment.posting_date)
			end_date = getdate(next_payment_date)

			for current_date in daterange(start_date, end_date):
				if current_date >= getdate(posting_date):
					matching_demand_found = False
					for d in demands:
						demand_amount = flt(d.demand_amount, precision)
						if d.demand_date <= current_date and demand_amount > 0:
							dpd_counter = date_diff(current_date, d.demand_date) + 1
							create_dpd_record(loan, demand.loan_disbursement, current_date, dpd_counter)
							matching_demand_found = True
							break

					if not matching_demand_found:
						create_dpd_record(loan, demand.loan_disbursement, current_date, 0)


def create_loan_write_off(loan, posting_date):
	if frappe.db.get_value("Loan", loan, "status") != "Written Off":
		loan_write_off = frappe.new_doc("Loan Write Off")
		loan_write_off.loan = loan
		loan_write_off.posting_date = posting_date
		loan_write_off.submit()


def create_dpd_record(
	loan, loan_disbursement, posting_date, days_past_due, process_loan_classification=None
):
	existing_log = frappe.db.get_value(
		"Days Past Due Log",
		{"loan": loan, "posting_date": posting_date, "loan_disbursement": loan_disbursement},
	)
	if existing_log:
		doc = frappe.get_doc("Days Past Due Log", existing_log)
	else:
		doc = frappe.new_doc("Days Past Due Log")

	doc.update(
		{
			"loan": loan,
			"loan_disbursement": loan_disbursement,
			"posting_date": posting_date,
			"days_past_due": days_past_due,
			"process_loan_classification": process_loan_classification,
		}
	)
	doc.save(ignore_permissions=True)


def update_loan_and_customer_status(
	loan,
	company,
	applicant_type,
	applicant,
	days_past_due,
	is_npa,
	posting_date,
	freeze_date=None,
	loan_disbursement=None,
	is_backdated=0,
	dpd_threshold=0,
	via_background_job=False,
):
	from lending.loan_management.doctype.loan_write_off.loan_write_off import (
		write_off_charges,
		write_off_suspense_entries,
	)

	loan_status, repayment_schedule_type, loan_product = frappe.db.get_value(
		"Loan", loan, ["status", "repayment_schedule_type", "loan_product"]
	)

	if loan_status == "Written Off":
		is_written_off = 1
	else:
		is_written_off = 0

	classification_code, classification_name = get_classification_code_and_name(
		days_past_due, company, is_written_off=is_written_off
	)

	if repayment_schedule_type == "Line of Credit":
		if loan_disbursement:
			frappe.db.set_value(
				"Loan Disbursement",
				loan_disbursement,
				{
					"days_past_due": days_past_due,
				},
				update_modified=False,
			)

		max_dpd = frappe.db.get_value(
			"Loan Disbursement",
			{
				"against_loan": loan,
				"docstatus": 1,
			},
			"max(days_past_due)",
		)
		days_past_due = max_dpd

	if loan_status == "Settled":
		write_off_suspense_entries(loan, loan_product, posting_date, company)
		write_off_charges(loan, posting_date, company)
	elif is_backdated and days_past_due < dpd_threshold:
		is_previous_npa = frappe.db.get_value(
			"Loan NPA Log",
			{"loan": loan, "npa_date": ("<", posting_date), "delinked": 0},
			"npa",
			order_by="npa_date desc",
		)
		max_date = frappe.db.get_value("Days Past Due Log", {"loan": loan}, "max(posting_date)")
		current_npa = frappe.db.get_value("Loan", loan, "is_npa")

		actual_diff = date_diff(getdate(max_date), getdate(posting_date))
		actual_dpd = days_past_due + actual_diff

		if (
			(not cint(is_previous_npa) and actual_dpd < dpd_threshold)
			or actual_dpd == 0
			or days_past_due == 0
		):
			frappe.db.set_value("Loan", loan, {"is_npa": 0, "days_past_due": actual_dpd})
			write_off_suspense_entries(loan, loan_product, max_date, company)
			write_off_charges(loan, max_date, company)
			create_loan_npa_log(loan, posting_date, 0, "Loan Repayment")
		elif cint(is_previous_npa) and not cint(current_npa):
			frappe.db.set_value("Loan", loan, "is_npa", 1)
			create_loan_npa_log(loan, posting_date, 1, "Loan Repayment")
			create_dpd_record(loan, loan_disbursement, posting_date, actual_dpd)
			move_unpaid_interest_to_suspense_ledger(loan, max_date)
			move_receivable_charges_to_suspense_ledger(loan, company, max_date)

	elif is_npa:
		for loan_id in get_all_active_loans_for_the_customer(applicant, applicant_type):
			prev_npa = frappe.db.get_value("Loan", loan_id, "is_npa")
			if not prev_npa:
				move_unpaid_interest_to_suspense_ledger(loan_id, posting_date)
				move_receivable_charges_to_suspense_ledger(loan_id, company, posting_date)

		update_all_linked_loan_customer_npa_status(
			is_npa, applicant_type, applicant, posting_date, loan, via_background_job=via_background_job
		)
	else:
		max_dpd = frappe.db.get_value(
			"Loan", {"applicant_type": applicant_type, "applicant": applicant}, ["MAX(days_past_due)"]
		)

		""" if max_dpd is greater than 0 loan still NPA, do nothing"""
		if max_dpd == 0 or freeze_date:
			prev_npa = frappe.db.get_value("Loan", loan, "is_npa")
			if prev_npa:
				for loan_id in get_all_active_loans_for_the_customer(applicant, applicant_type):
					loan_product = frappe.db.get_value("Loan", loan_id, "loan_product")
					write_off_suspense_entries(loan_id, loan_product, posting_date, company)
					write_off_charges(loan_id, posting_date, company)

				update_all_linked_loan_customer_npa_status(
					is_npa, applicant_type, applicant, posting_date, loan, via_background_job=via_background_job
				)

	frappe.db.set_value(
		"Loan",
		loan,
		{
			"days_past_due": days_past_due,
			"classification_code": classification_code,
			"classification_name": classification_name,
		},
		update_modified=False,
	)


def get_all_active_loans_for_the_customer(applicant, applicant_type):
	return frappe.get_all(
		"Loan",
		{
			"status": ("in", ["Disbursed", "Partially Disbursed", "Active"]),
			"docstatus": 1,
			"applicant_type": applicant_type,
			"applicant": applicant,
		},
		pluck="name",
	)


def update_all_linked_loan_customer_npa_status(
	is_npa,
	applicant_type,
	applicant,
	posting_date,
	loan=None,
	manual_npa=False,
	via_background_job=False,
):
	"""Update NPA status of all linked customers"""

	prev_npa = frappe.db.get_value("Loan", loan, "is_npa")

	if not via_background_job and prev_npa != is_npa:
		update_npa_check(is_npa, applicant_type, applicant, posting_date, manual_npa=manual_npa)
	else:
		update_value = {
			"is_npa": is_npa,
		}

		if manual_npa:
			update_value["manual_npa"] = manual_npa

		frappe.db.set_value("Loan", loan, update_value)

	frappe.db.set_value("Customer", applicant, "is_npa", is_npa)

	if loan:
		create_loan_npa_log(loan, posting_date, is_npa, "Background Job", manual_npa=manual_npa)


def update_npa_check(is_npa, applicant_type, applicant, posting_date, manual_npa=False):
	_loan = frappe.qb.DocType("Loan")
	query = (
		frappe.qb.from_(_loan)
		.select(_loan.name)
		.where(
			(_loan.docstatus == 1)
			& (_loan.unmark_npa == 0)
			& (_loan.status.isin(["Disbursed", "Partially Disbursed", "Active"]))
			& (_loan.applicant_type == applicant_type)
			& (_loan.applicant == applicant)
			& (_loan.watch_period_end_date.isnull() | _loan.watch_period_end_date < posting_date)
		)
	)

	query = query.for_update()
	loans = query.run(as_dict=1)

	for loan in loans:
		update_value = {
			"is_npa": is_npa,
		}

		if manual_npa:
			update_value["manual_npa"] = manual_npa

		frappe.db.set_value("Loan", loan.name, update_value)


def create_loan_npa_log(loan, posting_date, is_npa, event, manual_npa=None):
	loan_npa_log = frappe.new_doc("Loan NPA Log")
	loan_npa_log.loan = loan
	loan_npa_log.npa_date = posting_date
	loan_npa_log.npa = is_npa
	loan_npa_log.manual_npa = manual_npa
	if manual_npa:
		loan_npa_log.manual_npa_date = posting_date
	loan_npa_log.event = event
	loan_npa_log.save(ignore_permissions=True)


def update_watch_period_date_for_all_loans(watch_period_end_date, applicant_type, applicant):
	_loan = frappe.qb.DocType("Loan")
	frappe.qb.update(_loan).set(_loan.watch_period_end_date, watch_period_end_date).where(
		(_loan.docstatus == 1)
		& (_loan.status.isin(["Disbursed", "Partially Disbursed", "Active"]))
		& (_loan.applicant_type == applicant_type)
		& (_loan.applicant == applicant)
	).run()


def get_classification_code_and_name(days_past_due, company, is_written_off):
	classification_code = ""
	classification_name = ""

	ranges = frappe.get_all(
		"Loan Classification Range",
		fields=[
			"is_written_off",
			"min_dpd_range",
			"max_dpd_range",
			"classification_code",
			"classification_name",
		],
		filters={"parent": company},
		order_by="min_dpd_range",
	)

	for range in ranges:
		if range.min_dpd_range <= days_past_due <= range.max_dpd_range and cint(
			range.is_written_off
		) == cint(is_written_off):
			return range.classification_code, range.classification_name

	return classification_code, classification_name


@redis_cache(ttl=60 * 60)
def get_dpd_threshold_map():
	return frappe._dict(
		frappe.get_all("Loan Product", fields=["name", "days_past_due_threshold_for_npa"], as_list=1)
	)


@redis_cache(ttl=60 * 60)
def get_dpd_threshold_write_off_map():
	return frappe._dict(
		frappe.get_all(
			"Company", fields=["name", "days_past_due_threshold_for_auto_write_off"], as_list=1
		)
	)


@redis_cache(ttl=60 * 60)
def get_loan_partner_threshold_map():
	return frappe._dict(
		frappe.get_all("Loan Partner", fields=["name", "fldg_trigger_dpd"], as_list=1)
	)


def move_unpaid_interest_to_suspense_ledger(loan, posting_date=None):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		get_last_demand_date,
		get_unbooked_interest,
	)

	if not posting_date:
		posting_date = getdate()

	loan_product = frappe.db.get_value("Loan", loan, "loan_product")
	company = frappe.db.get_value("Loan", loan, "company")

	last_demand_date = get_last_demand_date(loan, posting_date)

	unbooked_interest, accrued_interest = get_unbooked_interest(
		loan, posting_date, last_demand_date=last_demand_date
	)

	accounts = frappe.db.get_value(
		"Loan Product",
		loan_product,
		[
			"interest_income_account",
			"interest_receivable_account",
			"penalty_receivable_account",
			"additional_interest_income",
			"additional_interest_receivable",
			"penalty_income_account",
			"suspense_interest_income",
			"penalty_suspense_account",
			"additional_interest_suspense",
		],
		as_dict=1,
	)

	amounts = frappe._dict(
		frappe.db.get_all(
			"GL Entry",
			fields=["account", "sum(credit) - sum(debit) as amount"],
			filters={
				"against_voucher_type": "Loan",
				"against_voucher": loan,
				"account": (
					"in",
					[
						accounts.interest_receivable_account,
						accounts.additional_interest_receivable,
						accounts.penalty_receivable_account,
					],
				),
				"is_cancelled": 0,
				"posting_date": ("<=", posting_date),
			},
			group_by="account",
			as_list=1,
		)
	)

	if abs(amounts.get(accounts.interest_receivable_account, 0)) > 0 or unbooked_interest > 0:
		amount = abs(amounts.get(accounts.interest_receivable_account, 0)) + unbooked_interest
		debit_account = accounts.interest_income_account
		credit_account = accounts.get("suspense_interest_income")
		make_journal_entry(posting_date, company, loan, amount, debit_account, credit_account)

	if abs(amounts.get(accounts.penalty_receivable_account, 0)) > 0:
		amount = abs(amounts.get(accounts.penalty_receivable_account, 0))
		debit_account = accounts.penalty_income_account
		credit_account = accounts.get("penalty_suspense_account")
		make_journal_entry(posting_date, company, loan, amount, debit_account, credit_account)

	if abs(amounts.get(accounts.additional_interest_receivable, 0)) > 0:
		amount = abs(amounts.get(accounts.additional_interest_receivable, 0))
		debit_account = accounts.additional_interest_income
		credit_account = accounts.get("additional_interest_suspense")
		make_journal_entry(posting_date, company, loan, amount, debit_account, credit_account)


def make_suspense_journal_entry(
	loan, company, loan_product, amount, posting_date, is_penal=False, additional_interest=0
):
	account_details = frappe.get_value(
		"Loan Product",
		loan_product,
		[
			"suspense_interest_income",
			"interest_income_account",
			"penalty_suspense_account",
			"penalty_income_account",
			"additional_interest_income",
			"additional_interest_suspense",
		],
		as_dict=1,
	)

	if account_details:
		if is_penal:
			debit_account = account_details.penalty_income_account
			credit_account = account_details.penalty_suspense_account
		else:
			debit_account = account_details.interest_income_account
			credit_account = account_details.suspense_interest_income

		if amount:
			amount = amount - additional_interest
			make_journal_entry(posting_date, company, loan, amount, debit_account, credit_account)

		if additional_interest > 0:
			make_journal_entry(
				posting_date,
				company,
				loan,
				additional_interest,
				account_details.additional_interest_income,
				account_details.additional_interest_suspense,
			)


def move_receivable_charges_to_suspense_ledger(loan, company, posting_date, invoice=None):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_unpaid_demands

	overdue_charges = get_unpaid_demands(
		loan, posting_date=posting_date, demand_type="Charges", sales_invoice=invoice
	)

	loan_product, applicant = frappe.db.get_value("Loan", loan, ["loan_product", "applicant"])

	charge_details = frappe.db.get_all(
		"Loan Charges",
		{"parent": loan_product},
		["charge_type", "income_account", "suspense_account", "receivable_account"],
	)

	charge_type_map = {}
	for d in charge_details:
		charge_type_map[d.charge_type] = d

	for charges in overdue_charges:
		income_account = charge_type_map.get(charges.demand_subtype, {}).get("income_account")
		suspense_account = charge_type_map.get(charges.demand_subtype, {}).get("suspense_account")
		receivable_account = charge_type_map.get(charges.demand_subtype, {}).get("receivable_account")
		base_amount = get_base_charge_amount(
			charges.demand_subtype,
			charges.outstanding_amount,
			company,
			loan,
			income_account,
			receivable_account,
			applicant,
		)

		if suspense_account:
			make_journal_entry(posting_date, company, loan, base_amount, income_account, suspense_account)


def get_base_charge_amount(
	charge_type, amount, company, loan, income_account, receivable_account, applicant
):
	from erpnext import get_default_currency

	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"loan": loan,
			"customer": applicant,
			"set_posting_time": 1,
			"company": company,
			"conversion_rate": 1,
			"currency": get_default_currency(),
			"due_date": getdate(),
		}
	)

	si.append(
		"items",
		{
			"item_code": charge_type,
			"rate": amount,
			"qty": 1,
			"income_account": income_account,
		},
	)

	si.debit_to = receivable_account
	si.set_missing_values()
	si.run_method("before_validate")
	si.validate()

	return si.base_net_total


def make_journal_entry(
	posting_date, company, loan, amount, debit_account, credit_account, is_reverse=0
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if not flt(amount, precision):
		return

	# Swap Accounts
	if is_reverse:
		debit_account, credit_account = credit_account, debit_account

	jv = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"posting_date": posting_date,
			"company": company,
			"accounts": [
				{
					"account": debit_account,
					"debit_in_account_currency": amount,
					"debit": amount,
					"reference_type": "Loan",
					"reference_name": loan,
					"cost_center": erpnext.get_default_cost_center(company),
				},
				{
					"account": credit_account,
					"credit_in_account_currency": amount,
					"credit": amount,
					"reference_type": "Loan",
					"reference_name": loan,
					"cost_center": erpnext.get_default_cost_center(company),
				},
			],
		}
	)

	jv.flags.ignore_validate = True
	jv.submit()


def get_unpaid_interest_amount(loan, posting_date, demand_subtype):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_unpaid_demands

	posting_date = posting_date or getdate()
	unpaid_demands = get_unpaid_demands(
		loan, posting_date=posting_date, demand_subtype=demand_subtype
	)

	amount = 0
	for demand in unpaid_demands:
		amount += demand.outstanding_amount

	return amount


def make_fldg_invocation_jv(loan, posting_date):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		get_pending_principal_amount,
	)

	loan_partner = frappe.db.get_value("Loan", loan, "loan_partner")
	partner_details = frappe.db.get_value(
		"Loan Partner",
		loan_partner,
		[
			"payable_account",
			"fldg_account",
			"partner_interest_share",
			"fldg_limit_calculation_component",
			"type_of_fldg_applicable",
			"fldg_fixed_deposit_percentage",
			"fldg_corporate_guarantee_percentage",
		],
		as_dict=1,
	)

	limit_amount = 0

	if partner_details.fldg_limit_calculation_component == "Disbursement":
		base_amount = frappe.db.get_value("Loan", loan, "disbursed_amount")
	elif partner_details.fldg_limit_calculation_component == "POS":
		base_amount = get_pending_principal_amount(loan)

	if partner_details.type_of_fldg_applicable == "Fixed Deposit Only":
		limit_amount += base_amount * partner_details.fldg_fixed_deposit_percentage / 100
	elif partner_details.type_of_fldg_applicable == "Corporate Guarantee Only":
		limit_amount += base_amount * partner_details.fldg_corporate_guarantee_percentage / 100
	elif partner_details.type_of_fldg_applicable == "Both Fixed Deposit and Corporate Guarantee":
		limit_amount += base_amount * partner_details.fldg_fixed_deposit_percentage / 100
		limit_amount += base_amount * partner_details.fldg_corporate_guarantee_percentage / 100

	if not partner_details.payable_account:
		frappe.throw(_("Please add partner Payable Account for Loan Partner {0}").format(loan_partner))

	if not partner_details.fldg_account:
		frappe.throw(_("Please add partner FLGD Account for Loan Partner {0}").format(loan_partner))

	if limit_amount:
		journal_entry = frappe.new_doc("Journal Entry")
		journal_entry.posting_date = posting_date

		journal_entry.append(
			"accounts",
			{
				"account": partner_details.payable_account,
				"credit_in_account_currency": limit_amount,
				"credit": limit_amount,
				"reference_type": "Loan",
				"reference_name": loan,
			},
		)

		journal_entry.append(
			"accounts",
			{
				"account": partner_details.fldg_account,
				"debit_in_account_currency": limit_amount,
				"debit": limit_amount,
				"reference_type": "Loan",
				"reference_name": loan,
			},
		)

		journal_entry.submit()


@frappe.whitelist()
def get_cyclic_date(loan_product, posting_date, ignore_bpi=False):
	cycle_day, min_days_bw_disbursement_first_repayment = frappe.db.get_value(
		"Loan Product",
		loan_product,
		["cyclic_day_of_the_month", "min_days_bw_disbursement_first_repayment"],
	)
	cycle_day = cint(cycle_day)

	last_day_of_month = get_last_day(posting_date)
	cyclic_date = add_days(last_day_of_month, cycle_day)

	if not ignore_bpi:
		broken_period_days = date_diff(cyclic_date, posting_date)
		if broken_period_days < min_days_bw_disbursement_first_repayment:
			cyclic_date = add_days(get_last_day(cyclic_date), cycle_day)

	return cyclic_date


def create_loan_feeze_log(loan, freeze_date, reason, unfreeze_date=None):
	frappe.get_doc(
		{
			"doctype": "Loan Freeze Log",
			"loan": loan,
			"freeze_date": freeze_date,
			"unfreeze_date": unfreeze_date,
			"reason_for_freezing": reason,
		}
	).insert(ignore_permissions=True)


def auto_close_loc_loans(posting_date=None):
	if not posting_date:
		posting_date = getdate()

	loc_loans = frappe.db.get_all(
		"Loan",
		{
			"docstatus": 1,
			"status": "Active",
			"repayment_schedule_type": "Line of Credit",
			"limit_applicable_end": ("<=", posting_date),
			"utilized_limit_amount": 0,
		},
		pluck="name",
	)

	loan = frappe.qb.DocType("Loan")

	if loc_loans:
		frappe.qb.update("Loan").set("status", "Closed").set("closure_date", posting_date).where(
			loan.name.isin(loc_loans)
		).run()


def get_voucher_subtypes(doc):
	voucher_subtypes = {
		"Loan Repayment": "repayment_type",
		"Loan Interest Accrual": "interest_type",
		"Loan Demand": "demand_subtype",
	}

	return doc.get(voucher_subtypes.get(doc.doctype))
