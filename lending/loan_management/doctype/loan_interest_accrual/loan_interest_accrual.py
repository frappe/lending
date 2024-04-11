# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_datetime, getdate, nowdate

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController


class LoanInterestAccrual(AccountsController):
	def validate(self):
		if not self.loan:
			frappe.throw(_("Loan is mandatory"))

		if not self.posting_date:
			self.posting_date = nowdate()

		if not self.interest_amount and not self.payable_principal_amount:
			frappe.throw(_("Interest Amount or Principal Amount is mandatory"))

		if not self.last_accrual_date:
			self.last_accrual_date = get_last_accrual_date(self.loan, self.posting_date)

	def on_submit(self):
		self.make_gl_entries()

	def on_cancel(self):
		if self.repayment_schedule_name:
			self.update_is_accrued()

		self.make_gl_entries(cancel=1)
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]

	def update_is_accrued(self):
		frappe.db.set_value("Repayment Schedule", self.repayment_schedule_name, "is_accrued", 0)

	def make_gl_entries(self, cancel=0, adv_adj=0):
		gle_map = []

		cost_center, loan_product = frappe.db.get_value(
			"Loan", self.loan, ["cost_center", "loan_product"]
		)

		account_details = frappe.db.get_value(
			"Loan Product",
			loan_product,
			["interest_receivable_account", "suspense_interest_receivable", "suspense_interest_income"],
			as_dict=1,
		)

		if self.is_npa:
			receivable_account = account_details.suspense_interest_receivable
			income_account = account_details.suspense_interest_income
		else:
			receivable_account = account_details.interest_receivable_account
			income_account = self.interest_income_account

		if self.interest_amount:
			gle_map.append(
				self.get_gl_dict(
					{
						"account": receivable_account,
						"party_type": self.applicant_type,
						"party": self.applicant,
						"against": income_account,
						"debit": self.interest_amount,
						"debit_in_account_currency": self.interest_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.loan,
						"remarks": _("Interest accrued from {0} to {1} against loan: {2}").format(
							self.last_accrual_date, self.posting_date, self.loan
						),
						"cost_center": cost_center,
						"posting_date": self.posting_date,
					}
				)
			)

			gle_map.append(
				self.get_gl_dict(
					{
						"account": income_account,
						"against": receivable_account,
						"credit": self.interest_amount,
						"credit_in_account_currency": self.interest_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.loan,
						"remarks": ("Interest accrued from {0} to {1} against loan: {2}").format(
							self.last_accrual_date, self.posting_date, self.loan
						),
						"cost_center": cost_center,
						"posting_date": self.posting_date,
					}
				)
			)

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj)


# For Eg: If Loan disbursement date is '01-09-2019' and disbursed amount is 1000000 and
# rate of interest is 13.5 then first loan interest accrual will be on '01-10-2019'
# which means interest will be accrued for 30 days which should be equal to 11095.89
def calculate_accrual_amount_for_demand_loans(
	loan, posting_date, process_loan_interest, accrual_type
):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		calculate_amounts,
		get_pending_principal_amount,
	)

	no_of_days = get_no_of_days_for_interest_accural(loan, posting_date)
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	if no_of_days <= 0:
		return

	pending_principal_amount = get_pending_principal_amount(loan)

	if loan.is_term_loan:
		pending_amounts = calculate_amounts(loan.name, posting_date)
		pending_principal_amount = pending_principal_amount - flt(
			pending_amounts["payable_principal_amount"]
		)
	else:
		pending_amounts = calculate_amounts(loan.name, posting_date, payment_type="Loan Closure")

	payable_interest = get_interest_amount(
		no_of_days, pending_principal_amount, loan.rate_of_interest, loan.company, posting_date
	)

	args = frappe._dict(
		{
			"loan": loan.name,
			"applicant_type": loan.applicant_type,
			"applicant": loan.applicant,
			"interest_income_account": loan.interest_income_account,
			"loan_account": loan.loan_account,
			"pending_principal_amount": pending_principal_amount,
			"interest_amount": payable_interest,
			"total_pending_interest_amount": pending_amounts["interest_amount"],
			"penalty_amount": pending_amounts["penalty_amount"],
			"process_loan_interest": process_loan_interest,
			"posting_date": posting_date,
			"due_date": posting_date,
			"accrual_type": accrual_type,
		}
	)

	if flt(payable_interest, precision) > 0.0:
		make_loan_interest_accrual_entry(args)


def make_accrual_interest_entry_for_demand_loans(
	posting_date,
	process_loan_interest=None,
	open_loans=None,
	loan_product=None,
	accrual_type="Regular",
	via_restructure=False,
):
	query_filters = {
		"status": ("in", ["Disbursed", "Partially Disbursed"]),
		"docstatus": 1,
	}

	if not via_restructure:
		query_filters.update({"is_term_loan": 0})

	if loan_product:
		query_filters.update({"loan_product": loan_product})

	if not open_loans:
		open_loans = frappe.get_all(
			"Loan",
			fields=[
				"name",
				"total_payment",
				"total_amount_paid",
				"debit_adjustment_amount",
				"credit_adjustment_amount",
				"refund_amount",
				"loan_account",
				"interest_income_account",
				"loan_amount",
				"is_term_loan",
				"status",
				"disbursement_date",
				"disbursed_amount",
				"applicant_type",
				"applicant",
				"rate_of_interest",
				"total_interest_payable",
				"written_off_amount",
				"total_principal_paid",
				"repayment_start_date",
				"company",
			],
			filters=query_filters,
		)

	for loan in open_loans:
		calculate_accrual_amount_for_demand_loans(
			loan, posting_date, process_loan_interest, accrual_type
		)


def make_accrual_interest_entry_for_term_loans(
	posting_date, process_loan_interest, term_loan=None, loan_product=None, accrual_type="Regular"
):
	curr_date = posting_date or add_days(nowdate(), 1)

	term_loans = get_term_loans(curr_date, term_loan, loan_product)

	accrued_entries = []

	for loan in term_loans:
		accrued_entries.append(loan.payment_entry)
		args = frappe._dict(
			{
				"loan": loan.name,
				"applicant_type": loan.applicant_type,
				"applicant": loan.applicant,
				"interest_income_account": loan.interest_income_account,
				"loan_account": loan.loan_account,
				"interest_amount": loan.interest_amount,
				"payable_principal": loan.principal_amount,
				"process_loan_interest": process_loan_interest,
				"repayment_schedule_name": loan.payment_entry,
				"posting_date": posting_date,
				"accrual_type": accrual_type,
				"due_date": loan.payment_date,
			}
		)

		make_loan_interest_accrual_entry(args)

	if accrued_entries:
		frappe.db.sql(
			"""UPDATE `tabRepayment Schedule`
			SET is_accrued = 1 where name in (%s)"""  # nosec
			% ", ".join(["%s"] * len(accrued_entries)),
			tuple(accrued_entries),
		)


def get_term_loans(date, term_loan=None, loan_product=None):
	loan = frappe.qb.DocType("Loan")
	loan_schedule = frappe.qb.DocType("Loan Repayment Schedule")
	loan_repayment_schedule = frappe.qb.DocType("Repayment Schedule")

	query = (
		frappe.qb.from_(loan)
		.inner_join(loan_schedule)
		.on(loan.name == loan_schedule.loan)
		.inner_join(loan_repayment_schedule)
		.on(loan_repayment_schedule.parent == loan_schedule.name)
		.select(
			loan.name,
			loan.total_payment,
			loan.total_amount_paid,
			loan.loan_account,
			loan.interest_income_account,
			loan.is_term_loan,
			loan.disbursement_date,
			loan.applicant_type,
			loan.applicant,
			loan.rate_of_interest,
			loan.total_interest_payable,
			loan.repayment_start_date,
			loan_repayment_schedule.name.as_("payment_entry"),
			loan_repayment_schedule.payment_date,
			loan_repayment_schedule.principal_amount,
			loan_repayment_schedule.interest_amount,
			loan_repayment_schedule.is_accrued,
			loan_repayment_schedule.balance_loan_amount,
		)
		.where(
			(loan.docstatus == 1)
			& (loan.status == "Disbursed")
			& (loan.is_term_loan == 1)
			& (loan_schedule.status == "Active")
			& (loan_repayment_schedule.principal_amount > 0)
			& (loan_repayment_schedule.payment_date <= date)
			& (loan_repayment_schedule.is_accrued == 0)
			& (loan_repayment_schedule.docstatus == 1)
		)
	)

	if term_loan:
		query = query.where(loan.name == term_loan)

	if loan_product:
		query = query.where(loan.loan_product == loan_product)

	term_loans = query.run(as_dict=1)

	return term_loans


def make_loan_interest_accrual_entry(args):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	loan_interest_accrual = frappe.new_doc("Loan Interest Accrual")
	loan_interest_accrual.loan = args.loan
	loan_interest_accrual.applicant_type = args.applicant_type
	loan_interest_accrual.applicant = args.applicant
	loan_interest_accrual.interest_income_account = args.interest_income_account
	loan_interest_accrual.loan_account = args.loan_account
	loan_interest_accrual.pending_principal_amount = flt(args.pending_principal_amount, precision)
	loan_interest_accrual.interest_amount = flt(args.interest_amount, precision)
	loan_interest_accrual.total_pending_interest_amount = flt(
		args.total_pending_interest_amount, precision
	)
	loan_interest_accrual.penalty_amount = flt(args.penalty_amount, precision)
	loan_interest_accrual.posting_date = args.posting_date or nowdate()
	loan_interest_accrual.process_loan_interest_accrual = args.process_loan_interest
	loan_interest_accrual.repayment_schedule_name = args.repayment_schedule_name
	loan_interest_accrual.payable_principal_amount = args.payable_principal
	loan_interest_accrual.accrual_type = args.accrual_type
	loan_interest_accrual.due_date = args.due_date

	loan_interest_accrual.save()
	loan_interest_accrual.submit()


def get_no_of_days_for_interest_accural(loan, posting_date):
	last_interest_accrual_date = get_last_accrual_date(loan.name, posting_date)

	no_of_days = date_diff(posting_date or nowdate(), last_interest_accrual_date) + 1

	return no_of_days


def get_last_accrual_date(loan, posting_date):
	last_posting_date = frappe.db.sql(
		""" SELECT MAX(posting_date) from `tabLoan Interest Accrual`
		WHERE loan = %s and docstatus = 1""",
		(loan),
	)

	if last_posting_date[0][0]:
		last_interest_accrual_date = last_posting_date[0][0]
		# interest for last interest accrual date is already booked, so add 1 day
		last_disbursement_date = get_last_disbursement_date(loan, posting_date)

		if last_disbursement_date and getdate(last_disbursement_date) > add_days(
			getdate(last_interest_accrual_date), 1
		):
			last_interest_accrual_date = last_disbursement_date

		return add_days(last_interest_accrual_date, 1)
	else:
		return frappe.db.get_value("Loan", loan, "disbursement_date")


def get_last_disbursement_date(loan, posting_date):
	last_disbursement_date = frappe.db.get_value(
		"Loan Disbursement",
		{"docstatus": 1, "against_loan": loan, "posting_date": ("<", posting_date)},
		"MAX(posting_date)",
	)

	return last_disbursement_date


def days_in_year(year):
	days = 365

	if (year % 4 == 0) and (year % 100 != 0) or (year % 400 == 0):
		days = 366

	return days


def get_per_day_interest(
	principal_amount, rate_of_interest, company, posting_date=None, interest_day_count_convention=None
):
	if not posting_date:
		posting_date = getdate()

	if not interest_day_count_convention:
		interest_day_count_convention = frappe.get_cached_value(
			"Company", company, "interest_day_count_convention"
		)

	if interest_day_count_convention == "Actual/365" or interest_day_count_convention == "30/365":
		year_divisor = 365
	elif interest_day_count_convention == "30/360" or interest_day_count_convention == "Actual/360":
		year_divisor = 360
	else:
		# Default is Actual/Actual
		year_divisor = days_in_year(get_datetime(posting_date).year)

	return flt((principal_amount * rate_of_interest) / (year_divisor * 100))


def get_interest_amount(
	no_of_days,
	principal_amount=None,
	rate_of_interest=None,
	company=None,
	posting_date=None,
	interest_per_day=None,
):
	interest_day_count_convention = frappe.get_cached_value(
		"Company", company, "interest_day_count_convention"
	)

	if not interest_per_day:
		interest_per_day = get_per_day_interest(
			principal_amount, rate_of_interest, company, posting_date, interest_day_count_convention
		)

	if interest_day_count_convention == "30/365" or interest_day_count_convention == "30/360":
		no_of_days = 30

	return interest_per_day * no_of_days
