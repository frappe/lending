# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json
from datetime import date, datetime

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
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
from frappe.utils.caching import redis_cache

import erpnext
from erpnext.accounts.doctype.journal_entry.journal_entry import get_payment_entry
from erpnext.accounts.general_ledger import process_gl_map

from lending.loan_management.controllers.loan_controller import LoanController
from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	make_loan_interest_accrual_entry,
)
from lending.loan_management.doctype.loan_limit_change_log.loan_limit_change_log import (
	create_loan_limit_change_log,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)
from lending.loan_management.utils import (
	loan_accounting_enabled,
	update_repayment_schedule_demand_generated,
)
from lending.utils import daterange


# nosemgrep
class Loan(LoanController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_disbursement_charge.loan_disbursement_charge import (
			LoanDisbursementCharge,
		)
		from lending.loan_management.doctype.loan_import_details.loan_import_details import (
			LoanImportDetails,
		)

		amended_from: DF.Link | None
		applicant: DF.DynamicLink
		applicant_name: DF.Data | None
		applicant_type: DF.Literal["Customer", "Employee"]
		auto_create_disbursement_on_loan_booking: DF.Check
		available_limit_amount: DF.Currency
		cancellation_date: DF.Date | None
		classification_code: DF.Link | None
		classification_name: DF.Data | None
		closure_date: DF.Date | None
		company: DF.Link
		cost_center: DF.Link | None
		credit_adjustment_amount: DF.Currency
		days_past_due: DF.Int
		debit_adjustment_amount: DF.Currency
		disbursed_amount: DF.Currency
		disbursement_account: DF.Link | None
		disbursement_date: DF.Date | None
		excess_amount_paid: DF.Currency
		fldg_trigger_date: DF.Date | None
		fldg_triggered: DF.Check
		freeze_account: DF.Check
		freeze_date: DF.Date | None
		interest_income_account: DF.Link | None
		is_imported: DF.Check
		is_npa: DF.Check
		is_secured_loan: DF.Check
		is_term_loan: DF.Check
		limit_applicable_end: DF.Date | None
		limit_applicable_start: DF.Date | None
		loan_account: DF.Link | None
		loan_amount: DF.Currency
		loan_application: DF.Link | None
		loan_category: DF.Link | None
		loan_charges: DF.Table[LoanDisbursementCharge]
		loan_import_details: DF.Table[LoanImportDetails]
		loan_partner: DF.Link | None
		loan_product: DF.Link
		loan_restructure_count: DF.Int
		manual_npa: DF.Check
		maximum_limit_amount: DF.Currency
		maximum_loan_amount: DF.Currency
		migration_date: DF.Date | None
		monthly_repayment_amount: DF.Currency
		moratorium_tenure: DF.Int
		moratorium_type: DF.Literal["", "EMI", "Principal"]
		payment_account: DF.Link | None
		penalty_charges_rate: DF.Percent
		penalty_income_account: DF.Link | None
		posting_date: DF.Date
		rate_of_interest: DF.Percent
		refund_amount: DF.Currency
		repayment_frequency: DF.Literal["Monthly", "Daily", "Weekly", "Bi-Weekly", "Quarterly", "One Time"]
		repayment_method: DF.Literal["", "Repay Fixed Amount per Period", "Repay Over Number of Periods"]
		repayment_periods: DF.Int
		repayment_schedule_type: DF.Data | None
		repayment_start_date: DF.Date | None
		settlement_date: DF.Date | None
		status: DF.Literal["", "Draft", "Sanctioned", "Partially Disbursed", "Disbursed", "Active", "Loan Closure Requested", "Closed", "Written Off", "Settled"]
		tenure_post_restructure: DF.Int
		total_amount_paid: DF.Currency
		total_interest_payable: DF.Currency
		total_payment: DF.Currency
		total_principal_paid: DF.Currency
		treatment_of_interest: DF.Literal["", "Capitalize", "Add to first repayment"]
		unmark_npa: DF.Check
		utilized_limit_amount: DF.Currency
		watch_period_end_date: DF.Date | None
		written_off_amount: DF.Currency
	# end: auto-generated types

	def validate(self):
		if frappe.flags.in_import:
			if not self.get("is_imported"):
				self.is_imported = 1

		self.set_status()
		self.set_loan_amount()
		self.validate_loan_amount()
		self.set_missing_fields()
		self.validate_loan_product()
		self.validate_employee()
		self.validate_cost_center()
		self.validate_accounts()
		self.check_sanctioned_amount_limit()
		self.set_cyclic_date()
		self.set_default_charge_account()
		self.set_available_limit_amount()
		self.validate_repayment_terms()

		if not self.is_term_loan or (self.is_term_loan and not self.is_new()):
			self.calculate_totals()

	def onload(self):
		if self.docstatus == 1:
			info = get_dashboard_info(self)
			self.set_onload("dashboard_info", info)

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

	def validate_accounts(self):
		if not loan_accounting_enabled(self.company):
			return

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
		if self.is_term_loan and self.repayment_method == "Repay Over Number of Periods":
			if not self.repayment_periods:
				frappe.throw(_("Repayment periods is mandatory for term loans"))

		if self.is_term_loan and self.repayment_schedule_type == "Flat Interest Rate":
			if self.repayment_method == "Repay Fixed Amount per Period":
				frappe.throw(
					_("Flat Interest Rate loans cannot have 'Repay Fixed Amount per Period' repayment method")
				)
			if self.repayment_frequency not in ("Monthly", "Yearly"):
				frappe.throw(
					_("Flat Interest Rate loans can only have monthly and yearly repayment frequency")
				)

	def get_migration_date_for_import(self):
		if not self.get("is_imported"):
			return None

		if not self.get("migration_date"):
			frappe.throw(_("Migration Date is mandatory for imported loans"))

		return self.get("migration_date")

	def is_line_of_credit_loan(self):
		return self.get("repayment_schedule_type") == "Line of Credit"

	def process_migrated_loan_after_submit(self):
		migration_date = self.get_migration_date_for_import()
		if not migration_date or self.get("status") == "Closed":
			return

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		is_loc = self.is_line_of_credit_loan()

		for d in (self.get("loan_import_details")):
			if is_loc:
				repayment_method = d.repayment_method
				repayment_frequency = d.repayment_frequency
				tenure = d.repayment_periods
				repayment_start_date = d.repayment_start_date
			else:
				repayment_method = self.get("repayment_method")
				repayment_frequency = self.get("repayment_frequency")
				tenure = self.get("repayment_periods")
				repayment_start_date = self.get("repayment_start_date")

			disb_name = self.import_loan_disbursement(
				d.loan_disbursement_id,
				d.disbursement_date,
				flt(d.disbursed_amount, precision),
				repayment_method,
				repayment_frequency,
				tenure,
				repayment_start_date,
				is_loc,
			)

			update_repayment_schedule_demand_generated(
				loan=self.name,
				loan_disbursement=disb_name,
				to_date=migration_date,
				demand_generated=1,
			)

			self.create_migrated_interest_accruals(
				disb_name,
				migration_date,
				flt(d.opening_principal_outstanding, precision),
				flt(d.opening_interest_outstanding, precision),
				flt(d.opening_penalty_outstanding, precision),
				flt(d.opening_additional_outstanding, precision),
			)

			components = [
				("EMI", "Principal", flt(d.opening_principal_outstanding, precision)),
				("EMI", "Interest", flt(d.opening_interest_outstanding, precision)),
				("Penalty", "Penalty", flt(d.opening_penalty_outstanding, precision)),
				("Additional Interest", "Additional Interest", flt(d.opening_additional_outstanding, precision)),
				("Charges", "Charges", flt(d.opening_charge_outstanding, precision)),
			]

			for demand_type, demand_subtype, amount in components:
				if flt(amount, precision) <= 0:
					continue

				create_loan_demand(
					loan=self.name,
					demand_date=migration_date,
					demand_type=demand_type,
					demand_subtype=demand_subtype,
					amount=flt(amount, precision),
					loan_disbursement=disb_name,
					posting_date=migration_date,
					paid_amount=0,
					is_imported=1,
				)

	def import_loan_disbursement(
		self,
		loan_disbursement_id,
		disbursement_date,
		disbursed_amount,
		repayment_method,
		repayment_frequency,
		tenure,
		repayment_start_date,
		is_loc,
	):
		data = {
			"doctype": "Loan Disbursement",
			"against_loan": self.name,
			"company": self.company,
			"loan_disbursement_id": loan_disbursement_id,
			"disbursement_date": disbursement_date,
			"posting_date": self.get("posting_date") or disbursement_date,
			"disbursed_amount": disbursed_amount,
			"is_imported": 1,
			"repayment_schedule_type": self.get("repayment_schedule_type"),
			"repayment_method": repayment_method,
			"repayment_frequency": repayment_frequency,
			"tenure": tenure,
			"repayment_start_date": repayment_start_date,
		}

		doc = frappe.get_doc(data)
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name

	def create_migrated_interest_accruals(
		self,
		disbursement_name,
		migration_date,
		principal_outstanding,
		interest_outstanding,
		penalty_outstanding,
		additional_outstanding,
	):
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		principal_outstanding = flt(principal_outstanding, precision)
		interest_outstanding = flt(interest_outstanding, precision)
		penalty_outstanding = flt(penalty_outstanding, precision)
		additional_outstanding = flt(additional_outstanding, precision)
		rate_of_interest = flt(self.get("rate_of_interest"), precision)

		if flt(interest_outstanding, precision) > 0:
			make_loan_interest_accrual_entry(
				loan=self.name,
				base_amount=principal_outstanding,
				interest_amount=interest_outstanding,
				process_loan_interest=0,
				start_date=migration_date,
				posting_date=migration_date,
				accrual_type="Regular",
				interest_type="Normal Interest",
				rate_of_interest=rate_of_interest,
				additional_interest=0,
				accrual_date=migration_date,
				loan_disbursement=disbursement_name,
				is_imported=1,
			)

		total_penal = flt(penalty_outstanding + additional_outstanding, precision)
		if flt(total_penal, precision) > 0:
			make_loan_interest_accrual_entry(
				loan=self.name,
				base_amount=0,
				interest_amount=total_penal,
				process_loan_interest=0,
				start_date=migration_date,
				posting_date=migration_date,
				accrual_type="Regular",
				interest_type="Penal Interest",
				rate_of_interest=rate_of_interest,
				additional_interest=total_penal,
				accrual_date=migration_date,
				loan_disbursement=disbursement_name,
				is_imported=1,
			)

	def on_submit(self):
		self.link_loan_security_assignment()
		# Interest accrual for backdated term loans
		self.create_loan_limit_change_log("Loan Booking", self.posting_date)
		self.process_migrated_loan_after_submit()

		if self.is_imported:
			self.make_gl_entries()

		if self.auto_create_disbursement_on_loan_booking:
			make_loan_disbursement(self.name, submit=True, posting_date=self.posting_date, disbursement_date=self.disbursement_date)

	def on_cancel(self):
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

		if self.is_imported:
			self.make_gl_entries(cancel=1)

	# nosemgrep
	def set_status(self):
		if self.is_imported and self.get("status") == "Closed":
			return

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
			)
			if self.manual_npa:
				move_unpaid_interest_to_suspense_ledger(self.name, value_date=getdate())

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

	def cancel_and_delete_repayment_schedule(self):
		schedules = frappe.db.get_all(
			"Loan Repayment Schedule", {"loan": self.name, "docstatus": 1}, pluck="name"
		)
		for schedule in schedules:
			schedule = frappe.get_doc("Loan Repayment Schedule", schedule)
			schedule.flags.ignore_links = True
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

		if not self.loan_amount and self.repayment_schedule_type != "Line of Credit":
			frappe.throw(_("Loan amount is mandatory"))

	def link_loan_security_assignment(self):
		if self.is_secured_loan and self.loan_application:
			lsa_details = frappe.db.get_value(
				"Loan Security Assignment",
				{
					"loan_application": self.loan_application,
					"status": "Pledge Requested",
					"docstatus": 1,
				},
				["name", "maximum_loan_value"],
			)

			if lsa_details:
				lsa, maximum_loan_value = lsa_details
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

	def cancel_loan_security_assignment(self):
		if not self.loan_application:
			for assignment in frappe.get_all(
				"Loan Security Assignment",
				filters={"loan": self.name, "status": "Pledged"},
				fields=["name"],
			):
				doc = frappe.get_doc("Loan Security Assignment", assignment.name)
				doc.cancel()

	def make_gl_entries(self, cancel=0, adv_adj=0):
		if not loan_accounting_enabled(self.company):
			return

		loan_account, payment_account = self.get_opening_accounts_from_loan_product()

		outstanding = self.get_outstanding_principal_amount()
		if outstanding <= 0:
			return

		posting_date = self.get_opening_posting_date()

		gle_map = []
		remarks = _("Opening entry for imported loan {0}").format(self.name)

		self.add_opening_gl_entry(
			gle_map=gle_map,
			account=payment_account,
			against_account=loan_account,
			amount=outstanding,
			remarks=remarks,
			posting_date=posting_date,
		)

		if gle_map:
			if cancel:
				gle_map = process_gl_map(gle_map)

			super().make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj)

	def get_outstanding_principal_amount(self) -> float:
		precision = cint(frappe.db.get_default("currency_precision")) or 2

		total_outstanding = sum(
			flt(row.opening_principal_outstanding)
			for row in self.get("loan_import_details") or []
		)

		return flt(total_outstanding, precision)

	def get_opening_posting_date(self):
		if self.get("migration_date"):
			return self.get("migration_date")

		return self.get("posting_date") or getdate()

	def get_opening_accounts_from_loan_product(self):
		accounts = frappe.db.get_value(
			"Loan Product",
			self.loan_product,
			["loan_account", "payment_account"],
			as_dict=True,
		) or {}

		if not accounts.get("loan_account"):
			frappe.throw(
				_("Please set Loan Account for the Loan Product {0}").format(frappe.bold(self.loan_product))
			)

		if not accounts.get("payment_account"):
			frappe.throw(
				_("Please set Payment Account for the Loan Product {0}").format(frappe.bold(self.loan_product))
			)

		return accounts.get("loan_account"), accounts.get("payment_account")

	def add_opening_gl_entry(
		self,
		gle_map,
		account,
		against_account,
		amount,
		remarks,
		posting_date,
	):
		account_type = frappe.db.get_value("Account", account, "account_type")

		gle_map.append(
			self.get_gl_dict(
				{
					"account": account,
					"against": against_account,
					"debit": amount,
					"debit_in_account_currency": amount,
					"credit": 0,
					"credit_in_account_currency": 0,
					"voucher_type": "Loan",
					"voucher_no": self.name,
					"remarks": remarks,
					"cost_center": self.get("cost_center"),
					"party_type": self.applicant_type if account_type in ("Receivable", "Payable") else None,
					"party": self.applicant if account_type in ("Receivable", "Payable") else None,
					"posting_date": posting_date,
					"is_opening": "Yes",
				}
			)
		)

		account_type = frappe.db.get_value("Account", against_account, "account_type")

		gle_map.append(
			self.get_gl_dict(
				{
					"account": against_account,
					"against": account,
					"debit": -1 * amount,  # negative debit becomes credit
					"debit_in_account_currency": -1 * amount,
					"credit": 0,
					"credit_in_account_currency": 0,
					"voucher_type": "Loan",
					"voucher_no": self.name,
					"remarks": remarks,
					"cost_center": self.get("cost_center"),
					"party_type": self.applicant_type if account_type in ("Receivable", "Payable") else None,
					"party": self.applicant if account_type in ("Receivable", "Payable") else None,
					"posting_date": posting_date,
					"is_opening": "Yes",
				}
			)
		)


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

	LoanInterestAccrual = DocType("Loan Interest Accrual")
	LoanRepayment = DocType("Loan Repayment")

	total_interest_amount = (
		frappe.qb.from_(LoanInterestAccrual)
		.select(fn.Sum(LoanInterestAccrual.interest_amount))
		.where(
			(LoanInterestAccrual.applicant_type == applicant_type)
			& (LoanInterestAccrual.company == company)
			& (LoanInterestAccrual.applicant == applicant)
			& (LoanInterestAccrual.docstatus == 1)
		)
	).run()[0][0] or 0

	paid_interest = (
		frappe.qb.from_(LoanRepayment)
		.select(fn.Sum(LoanRepayment.total_interest_paid))
		.where(
			(LoanRepayment.applicant_type == applicant_type)
			& (LoanRepayment.company == company)
			& (LoanRepayment.applicant == applicant)
			& (LoanRepayment.docstatus == 1)
		)
	).run()[0][0] or 0

	interest_amount = total_interest_amount - paid_interest

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
def request_loan_closure(loan: str, posting_date: str | None = None, auto_close: int = 0):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	frappe.has_permission("Loan", "write", throw=True)

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	if not posting_date:
		posting_date = getdate()

	amounts = calculate_amounts(loan, posting_date)
	pending_amount = (
		amounts["pending_principal_amount"]
		+ amounts["interest_amount"]
		+ amounts["penalty_amount"]
		- amounts.get("excess_amount_paid", 0)
	)

	loan_product, loan_status = frappe.get_value("Loan", loan, ["loan_product", "status"])

	write_off_limit = frappe.get_value("Loan Product", loan_product, "write_off_amount")

	if pending_amount and abs(pending_amount) < write_off_limit or loan_status == "Settled":
		# Auto create loan write off and update status as loan closure requested
		write_off = make_loan_write_off(loan, posting_date=posting_date)
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
def close_unsecured_term_loan(loan: str):
	frappe.has_permission("Loan", "write", throw=True)

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
	loan: str,
	disbursement_amount: float | None = None,
	as_dict: int | None = 0,
	submit: bool | None = False,
	repayment_start_date: str | None = None,
	repayment_frequency: str | None = None,
	posting_date: str | None = None,
	disbursement_date: str | None = None,
	bank_account: str | None = None,
	is_term_loan: int | None = None,
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
	disbursement_entry.repayment_start_date = repayment_start_date or loan_doc.repayment_start_date
	disbursement_entry.repayment_frequency = repayment_frequency or loan_doc.repayment_frequency
	disbursement_entry.disbursed_amount = disbursement_amount or loan_doc.loan_amount
	disbursement_entry.is_term_loan = is_term_loan or loan_doc.is_term_loan
	disbursement_entry.repayment_schedule_type = loan_doc.repayment_schedule_type

	if loan_doc.repayment_schedule_type != "Line of Credit":
		disbursement_entry.repayment_method = loan_doc.repayment_method

	for charge in loan_doc.get("loan_charges"):
		disbursement_entry.append(
			"loan_disbursement_charges",
			{
				"charge": charge.charge,
				"amount": charge.amount,
				"account": charge.account,
				"treatment_of_charge": charge.treatment_of_charge,
			},
		)

	if submit:
		disbursement_entry.submit()

	if as_dict:
		return disbursement_entry.as_dict()
	else:
		return disbursement_entry


@frappe.whitelist()
def make_repayment_entry(
	loan, applicant_type, applicant, loan_product, company, loan_disbursement=None, as_dict=0
):
	repayment_entry = frappe.new_doc("Loan Repayment")
	repayment_entry.against_loan = loan
	repayment_entry.applicant_type = applicant_type
	repayment_entry.applicant = applicant
	repayment_entry.company = company
	repayment_entry.loan_product = loan_product
	repayment_entry.posting_date = nowdate()
	repayment_entry.value_date = nowdate()
	repayment_entry.loan_disbursement = loan_disbursement

	if as_dict:
		return repayment_entry.as_dict()
	else:
		return repayment_entry


@frappe.whitelist()
def make_loan_write_off(loan: str, company: str | None = None, posting_date: str | None = None, amount: float = 0, as_dict: int = 0):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

	frappe.has_permission("Loan Write Off", "write", throw=True)

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
	write_off.is_settlement_write_off = 1
	write_off.save()

	if as_dict:
		return write_off.as_dict()
	else:
		return write_off


@frappe.whitelist()
def unpledge_security(
	loan: str | None = None,
	loan_security_assignment: str | None = None,
	security_map: dict| None = None,
	as_dict: int = 0,
	save: int = 0,
	submit: int = 0,
	approve: int = 0,
):
	# if no security_map is passed it will be considered as full unpledge
	if security_map and isinstance(security_map, str):
		security_map = json.loads(security_map)

	if loan:
		pledge_qty_map = security_map or get_pledged_security_qty(loan=loan)
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
	loans = frappe.get_list("Loan Security Shortfall", {"status": "Pending"}, pluck="loan")
	applicants = set(frappe.get_list("Loan", {"name": ("in", loans)}, pluck="name"))

	return {"value": len(applicants), "fieldtype": "Int"}


@frappe.whitelist()
def make_refund_jv(loan: str, amount: float = 0, reference_number: str | None = None, reference_date: str | None = None, submit: int = 0):
	frappe.has_permission("Journal Entry", "write", throw=True)

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
	loan_name: str,
	posting_date: str | date | datetime | None = None,
	loan_product: str | None = None,
	process_loan_classification: str | None = None,
	loan_disbursement: str | None = None,
	ignore_freeze: bool = False,
	is_backdated: bool = False,
	force_update_dpd_in_loan: bool = False,
) -> None:
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_unpaid_demands

	frappe.has_permission("Loan", "write", throw=True)

	"""Update days past due in loans"""
	posting_date = posting_date or getdate()

	if not loan_product:
		loan_product = frappe.get_value("Loan", loan_name, "loan_product")

	filters = {
		"loan": loan_name,
		"status": ("in", ["Active", "Closed"]),
		"docstatus": 1,
	}

	if loan_disbursement:
		filters["loan_disbursement"] = loan_disbursement

	disbursements = frappe.db.get_all("Loan Repayment Schedule", filters, pluck="loan_disbursement")

	for disbursement in disbursements:
		if getdate(posting_date) >= add_days(getdate(), -1) or force_update_dpd_in_loan:
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
					process_loan_classification=process_loan_classification,
				)
			else:
				frappe.enqueue(
					repost_days_past_due_log,
					loan=loan_name,
					posting_date=posting_date,
					loan_product=loan_product,
					loan_disbursement=disbursement,
					process_loan_classification=process_loan_classification,
					queue="long",
					enqueue_after_commit=True,
				)

			return

		threshold_map = get_dpd_threshold_map()
		threshold_write_off_map = get_dpd_threshold_write_off_map()

		loan_details = frappe.db.get_value(
			"Loan", loan_name, ["applicant_type", "applicant", "freeze_date", "company", "watch_period_end_date"], as_dict=1
		)

		applicant_type = loan_details.get("applicant_type")
		applicant = loan_details.get("applicant")
		company = loan_details.get("company")
		freeze_date = loan_details.get("freeze_date")
		existing_watch_period_end_date = loan_details.get("watch_period_end_date")

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
				)

			watch_period_days = frappe.db.get_value(
				"Company", company, "watch_period_post_loan_restructure_in_days"
			)

			restructure_exists = frappe.db.exists(
				"Loan Restructure",
				{
					"loan": loan_name,
					"status": "Approved",
					"docstatus": 1,
					"company": company,
					"restructure_type": "Normal Restructure",
				},
			)

			watch_period_start_date = (
				demand.demand_date
				if existing_watch_period_end_date and days_past_due == 1
				else getdate(posting_date)
				if is_npa and not existing_watch_period_end_date and restructure_exists
				else None
			)

			if watch_period_start_date:
				watch_period_end_date = add_days(watch_period_start_date, watch_period_days)
				update_watch_period_date_for_all_loans(
					watch_period_end_date, applicant_type, applicant
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
			)
			create_dpd_record(loan_name, disbursement, posting_date, 0, process_loan_classification)


def repost_days_past_due_log(
	loan, posting_date, loan_product, loan_disbursement, process_loan_classification
):
	"""Get outstanding demands for a loan"""
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	LoanDemand = DocType("Loan Demand")
	LoanRepayment = DocType("Loan Repayment")

	demand_query = (
		frappe.qb.from_(LoanDemand)
		.select(
			LoanDemand.demand_date,
			LoanDemand.loan_disbursement,
			LoanDemand.demand_subtype,
			Sum(LoanDemand.demand_amount).as_("demand_amount"),
			Sum(LoanDemand.outstanding_amount).as_("outstanding_amount"),
		)
		.where(
			(LoanDemand.loan == loan) & (LoanDemand.docstatus == 1) & (LoanDemand.demand_type == "EMI")
		)
		.groupby(LoanDemand.demand_date, LoanDemand.demand_subtype)
		.orderby(LoanDemand.demand_date)
	)

	if loan_product:
		demand_query = demand_query.where(LoanDemand.loan_product == loan_product)

	if loan_disbursement:
		demand_query = demand_query.where(LoanDemand.loan_disbursement == loan_disbursement)

	demands = demand_query.run(as_dict=True)

	if demands:
		repayment_schedule_type = frappe.db.get_value("Loan", loan, "repayment_schedule_type")

		payment_query = (
			frappe.qb.from_(LoanRepayment)
			.select(
				LoanRepayment.value_date,
				Sum(LoanRepayment.principal_amount_paid).as_("total_principal_paid"),
				Sum(LoanRepayment.total_interest_paid).as_("total_interest_paid"),
			)
			.where((LoanRepayment.against_loan == loan) & (LoanRepayment.docstatus == 1))
			.groupby(LoanRepayment.value_date)
			.orderby(LoanRepayment.value_date)
		)

		if loan_product:
			payment_query = payment_query.where(LoanRepayment.loan_product == loan_product)

		if loan_disbursement and repayment_schedule_type == "Line of Credit":
			payment_query = payment_query.where(LoanRepayment.loan_disbursement == loan_disbursement)

		payment_against_demand = payment_query.run(as_dict=True)

		for idx, payment in enumerate(payment_against_demand):
			next_payment_date = (
				payment_against_demand[idx + 1].value_date
				if idx + 1 < len(payment_against_demand)
				else getdate()
			)
			for demand in demands:
				if getdate(demand.demand_date) <= getdate(payment.value_date):
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

			start_date = getdate(payment.value_date)
			end_date = getdate(next_payment_date)

			for current_date in daterange(start_date, end_date):
				final_dpd = 0
				if current_date >= getdate(posting_date):
					matching_demand_found = False
					for d in demands:
						demand_amount = flt(d.demand_amount, precision)
						if getdate(d.demand_date) <= current_date and demand_amount > 0:
							dpd_counter = date_diff(current_date, d.demand_date) + 1
							create_dpd_record(
								loan, demand.loan_disbursement, current_date, dpd_counter, process_loan_classification
							)
							final_dpd = dpd_counter
							matching_demand_found = True
							break

					if not matching_demand_found:
						final_dpd = 0
						create_dpd_record(
							loan, demand.loan_disbursement, current_date, 0, process_loan_classification
						)

			frappe.db.set_value("Loan", loan, "days_past_due", final_dpd)


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
		doc = frappe.get_doc("Days Past Due Log", existing_log, for_update=True)
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
):
	from lending.loan_management.doctype.loan_write_off.loan_write_off import (
		write_off_charges,
		write_off_suspense_entries,
	)

	loan_details = frappe.db.get_value(
		"Loan", loan, ["status", "repayment_schedule_type", "loan_product", "unmark_npa", "is_npa",
			"watch_period_end_date", "classification_code", "classification_name"], as_dict=1)

	if loan_details.get("status") == "Written Off":
		is_written_off = 1
	else:
		is_written_off = 0

	if loan_details.get("watch_period_end_date") and getdate(loan_details.get("watch_period_end_date")) >= getdate(posting_date):
		classification_code = loan_details.get("classification_code")
		classification_name = loan_details.get("classification_name")
	else:
		classification_code, classification_name = get_classification_code_and_name(
			days_past_due, company, is_written_off=is_written_off
		)

	if loan_details.get("repayment_schedule_type") == "Line of Credit":
		if loan_disbursement:
			frappe.db.set_value(
				"Loan Disbursement",
				loan_disbursement,
				{
					"days_past_due": days_past_due,
				},
				update_modified=False,
			)

		LoanDisbursement = DocType("Loan Disbursement")
		max_dpd = (
			frappe.qb.from_(LoanDisbursement)
			.select(fn.Max(LoanDisbursement.days_past_due))
			.where((LoanDisbursement.against_loan == loan) & (LoanDisbursement.docstatus == 1))
		).run()[0][0] or 0

		days_past_due = max_dpd

	if loan_details.get("status") == "Settled":
		write_off_suspense_entries(loan, loan_details.get("loan_product"), posting_date, posting_date, company)
		write_off_charges(loan, posting_date, posting_date, company)
	elif is_backdated and days_past_due < dpd_threshold:
		is_previous_npa = frappe.db.get_value(
			"Loan NPA Log",
			{"loan": loan, "npa_date": ("<", posting_date), "delinked": 0},
			"npa",
			order_by="npa_date desc",
		)

		DaysPastDueLog = DocType("Days Past Due Log")
		max_date = (
			frappe.qb.from_(DaysPastDueLog)
			.select(fn.Max(DaysPastDueLog.posting_date))
			.where(DaysPastDueLog.loan == loan)
		).run()[0][0]

		actual_diff = date_diff(getdate(max_date), getdate(posting_date))
		actual_dpd = days_past_due + actual_diff

		if (
			(not cint(is_previous_npa) and actual_dpd < dpd_threshold)
			or actual_dpd == 0
			or days_past_due == 0
		):
			update_all_linked_loan_customer_npa_status(
				0, applicant_type, applicant, posting_date, loan, event="Loan Repayment"
			)
			write_off_suspense_entries(loan, loan_details.get("loan_product"), max_date, max_date, company)
			write_off_charges(loan, max_date, max_date, company)
		elif cint(is_previous_npa) and not cint(loan_details.get("current_npa")) and not cint(loan_details.get("unmark_npa")):
			update_all_linked_loan_customer_npa_status(
				1, applicant_type, applicant, posting_date, loan, event="Loan Repayment"
			)
			create_dpd_record(loan, loan_disbursement, posting_date, actual_dpd)
			move_unpaid_interest_to_suspense_ledger(loan, max_date, max_date)
			move_receivable_charges_to_suspense_ledger(loan, company, max_date, max_date)

	elif is_npa and not cint(loan_details.get("unmark_npa")) and not cint(loan_details.get("current_npa")):
		for loan_id in get_all_active_loans_for_the_customer(applicant, applicant_type):
			prev_npa = frappe.db.get_value("Loan", loan_id, "is_npa")
			if not prev_npa:
				move_unpaid_interest_to_suspense_ledger(loan_id, posting_date, value_date=posting_date)
				move_receivable_charges_to_suspense_ledger(loan_id, company, posting_date, posting_date)

		update_all_linked_loan_customer_npa_status(is_npa, applicant_type, applicant, posting_date, loan)
	else:
		Loan = DocType("Loan")

		max_dpd = (
			frappe.qb.from_(Loan)
			.select(fn.Max(Loan.days_past_due))
			.where((Loan.applicant_type == applicant_type) & (Loan.applicant == applicant))
		).run()[0][0] or 0

		""" if max_dpd is greater than 0 loan still NPA, do nothing"""
		if max_dpd == 0 or freeze_date:
			prev_npa = frappe.db.get_value("Loan", loan, "is_npa")
			if prev_npa:
				for loan_id in get_all_active_loans_for_the_customer(applicant, applicant_type):
					loan_product = frappe.db.get_value("Loan", loan_id, "loan_product")
					write_off_suspense_entries(loan_id, loan_product, posting_date, posting_date, company)
					write_off_charges(loan_id, posting_date, posting_date, company)

				update_all_linked_loan_customer_npa_status(
					is_npa, applicant_type, applicant, posting_date, loan
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
	event="Background Job",
):
	"""Update NPA status of all linked customers"""

	prev_npa = frappe.db.get_value("Loan", loan, "is_npa")

	if prev_npa != is_npa:
		update_npa_check(
			is_npa, applicant_type, applicant, posting_date, manual_npa=manual_npa, event=event
		)
		frappe.db.set_value("Customer", applicant, "is_npa", is_npa)


def update_npa_check(
	is_npa, applicant_type, applicant, posting_date, manual_npa=False, event=None
):
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
			& (_loan.watch_period_end_date.isnull() | (_loan.watch_period_end_date < posting_date))
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
		create_loan_npa_log(loan.name, posting_date, is_npa, event, manual_npa=manual_npa)


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


def move_unpaid_interest_to_suspense_ledger(loan, posting_date=None, value_date=None):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		get_last_demand_date,
		get_unbooked_interest,
	)

	if not posting_date:
		posting_date = getdate()

	loan_product = frappe.db.get_value("Loan", loan, "loan_product")
	company = frappe.db.get_value("Loan", loan, "company")

	last_demand_date = get_last_demand_date(loan, posting_date)

	unbooked_interest = get_unbooked_interest(loan, posting_date, last_demand_date=last_demand_date)

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

	GL = DocType("GL Entry")

	rows = (
		frappe.qb.from_(GL)
		.select(
			GL.account,
			fn.Sum(GL.credit).as_("credit"),
			fn.Sum(GL.debit).as_("debit"),
		)
		.where(
			(GL.against_voucher_type == "Loan")
			& (GL.against_voucher == loan)
			& (
				GL.account.isin(
					[
						accounts.interest_receivable_account,
						accounts.additional_interest_receivable,
						accounts.penalty_receivable_account,
					]
				)
			)
			& (GL.is_cancelled == 0)
			& (GL.posting_date <= posting_date)
		)
		.groupby(GL.account)
	).run(as_dict=True)

	amounts = frappe._dict()
	for row in rows:
		account = row["account"]
		credit = row.get("credit") or 0
		debit = row.get("debit") or 0
		amount = credit - debit
		amounts[account] = amount

	if abs(amounts.get(accounts.interest_receivable_account, 0)) > 0 or unbooked_interest > 0:
		amount = abs(amounts.get(accounts.interest_receivable_account, 0)) + unbooked_interest
		debit_account = accounts.interest_income_account
		credit_account = accounts.get("suspense_interest_income")
		make_journal_entry(
			posting_date,
			value_date,
			company,
			loan,
			amount,
			debit_account,
			credit_account,
			remark="Move overdue normal interest to suspense ledger",
		)

	if abs(amounts.get(accounts.penalty_receivable_account, 0)) > 0:
		amount = abs(amounts.get(accounts.penalty_receivable_account, 0))
		debit_account = accounts.penalty_income_account
		credit_account = accounts.get("penalty_suspense_account")
		make_journal_entry(
			posting_date,
			value_date,
			company,
			loan,
			amount,
			debit_account,
			credit_account,
			remark="Move overdue penal interest to suspense ledger",
		)

	if abs(amounts.get(accounts.additional_interest_receivable, 0)) > 0:
		amount = abs(amounts.get(accounts.additional_interest_receivable, 0))
		debit_account = accounts.additional_interest_income
		credit_account = accounts.get("additional_interest_suspense")
		make_journal_entry(
			posting_date,
			value_date,
			company,
			loan,
			amount,
			debit_account,
			credit_account,
			remark="Move overdue additional interest to suspense ledger",
		)


def make_suspense_journal_entry(
	loan,
	company,
	loan_product,
	amount,
	posting_date,
	value_date,
	is_penal=False,
	additional_interest=0,
):
	if not loan_accounting_enabled(company):
		return None, None

	account_details = frappe.get_value(
		"Loan Product",
		loan_product,
		(
			"suspense_interest_income",
			"interest_income_account",
			"penalty_suspense_account",
			"penalty_income_account",
			"additional_interest_income",
			"additional_interest_suspense",
		),
		as_dict=1,
		cache=True,
	)

	normal_penal_interest_jv = None
	additional_interest_jv = None

	if account_details:
		if is_penal:
			debit_account = account_details.penalty_income_account
			credit_account = account_details.penalty_suspense_account
		else:
			debit_account = account_details.interest_income_account
			credit_account = account_details.suspense_interest_income

		if amount:
			amount = amount - additional_interest
			normal_penal_interest_jv = make_journal_entry(
				posting_date, value_date, company, loan, amount, debit_account, credit_account
			)

		if additional_interest > 0:
			additional_interest_jv = make_journal_entry(
				posting_date,
				value_date,
				company,
				loan,
				additional_interest,
				account_details.additional_interest_income,
				account_details.additional_interest_suspense,
			)

	return normal_penal_interest_jv, additional_interest_jv


def move_receivable_charges_to_suspense_ledger(
	loan, company, posting_date, value_date, invoice=None
):
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
			make_journal_entry(
				posting_date, value_date, company, loan, base_amount, income_account, suspense_account
			)


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
	posting_date,
	value_date,
	company,
	loan,
	amount,
	debit_account,
	credit_account,
	is_reverse=0,
	remark=None,
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if not flt(amount, precision):
		return

	if not loan_accounting_enabled(company):
		return None

	# Swap Accounts
	if is_reverse:
		debit_account, credit_account = credit_account, debit_account

	jv = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"posting_date": posting_date,
			"value_date": value_date,
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
			"remarks": remark,
		}
	)

	jv.flags.ignore_validate = True
	jv.submit()

	return jv.name


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


def get_dashboard_info(loan):
	loan_info = {}
	loan_info["total_principal"] = flt(loan.total_payment) - flt(loan.total_interest_payable)
	loan_info["pending_principal"] = (
		flt(loan.total_payment) - flt(loan.total_interest_payable) - flt(loan.total_principal_paid)
	)
	loan_info["currency"] = frappe.get_cached_value("Company", loan.company, "default_currency")

	return loan_info
