# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_datetime, getdate, nowdate

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand


class LoanInterestAccrual(AccountsController):
	def validate(self):
		if not self.posting_date:
			self.posting_date = nowdate()

		if not self.interest_amount:
			frappe.throw(_("Interest Amount is mandatory"))

		if not self.last_accrual_date:
			self.last_accrual_date = get_last_accrual_date(self.loan, self.posting_date, self.interest_type)

	def on_submit(self):
		from lending.loan_management.doctype.loan.loan import make_suspense_journal_entry

		self.make_gl_entries()
		if self.is_npa:
			if self.interest_type == "Normal Interest":
				is_penal = False
			else:
				is_penal = True

			loan_status = frappe.db.get_value("Loan", self.loan, "status")

			if loan_status != "Written Off":
				make_suspense_journal_entry(
					self.loan,
					self.company,
					self.loan_product,
					self.interest_amount,
					self.posting_date,
					is_penal=is_penal,
					additional_interest=self.additional_interest_amount,
				)

	def on_cancel(self):
		self.make_gl_entries(cancel=1)
		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]

	def make_gl_entries(self, cancel=0, adv_adj=0):
		gle_map = []

		loan_status = frappe.db.get_value("Loan", self.loan, "status")

		if loan_status == "Written Off":
			return

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		cost_center = frappe.db.get_value("Loan", self.loan, "cost_center")
		account_details = frappe.db.get_value(
			"Loan Product",
			self.loan_product,
			[
				"interest_accrued_account",
				"interest_income_account",
				"penalty_accrued_account",
				"penalty_income_account",
				"additional_interest_income",
				"additional_interest_accrued",
			],
			as_dict=1,
		)

		if self.interest_type == "Normal Interest":
			receivable_account = account_details.interest_accrued_account
			income_account = self.interest_income_account or account_details.interest_income_account

			if not receivable_account:
				frappe.throw(
					_("Please set Interest Accrued Account in Loan Product {0}").format(self.loan_product)
				)

			if not income_account:
				frappe.throw(
					_("Please set Interest Income Account in Loan Product {0}").format(self.loan_product)
				)
		else:
			receivable_account = account_details.penalty_accrued_account
			income_account = account_details.penalty_income_account

			if not receivable_account:
				frappe.throw(
					_("Please set Penalty Accrued Account in Loan Product {0}").format(self.loan_product)
				)

			if not income_account:
				frappe.throw(
					_("Please set Penalty Income Account in Loan Product {0}").format(self.loan_product)
				)

		if self.additional_interest_amount:
			if not account_details.additional_interest_income:
				frappe.throw(
					_("Please set Additional Interest Income Account in Loan Product {0}").format(
						self.loan_product
					)
				)

			if not account_details.additional_interest_accrued:
				frappe.throw(
					_("Please set Additional Interest Accrued Account in Loan Product {0}").format(
						self.loan_product
					)
				)

		if self.interest_amount:
			final_interest_amount = self.interest_amount - self.additional_interest_amount
			if flt(final_interest_amount, precision):
				gle_map.append(
					self.get_gl_dict(
						{
							"account": receivable_account,
							"against": income_account,
							"debit": final_interest_amount,
							"debit_in_account_currency": final_interest_amount,
							"against_voucher_type": "Loan",
							"against_voucher": self.loan,
							"remarks": _("Interest accrued from {0} to {1} against loan: {2}").format(
								self.last_accrual_date, self.posting_date, self.loan
							),
							"cost_center": cost_center,
							"posting_date": self.accrual_date or self.posting_date,
						}
					)
				)

				gle_map.append(
					self.get_gl_dict(
						{
							"account": income_account,
							"against": receivable_account,
							"credit": final_interest_amount,
							"credit_in_account_currency": final_interest_amount,
							"against_voucher_type": "Loan",
							"against_voucher": self.loan,
							"remarks": ("Interest accrued from {0} to {1} against loan: {2}").format(
								self.last_accrual_date, self.posting_date, self.loan
							),
							"cost_center": cost_center,
							"posting_date": self.accrual_date or self.posting_date,
						}
					)
				)

		if flt(self.additional_interest_amount, precision):
			gle_map.append(
				self.get_gl_dict(
					{
						"account": account_details.additional_interest_accrued,
						"against": account_details.additional_interest_income,
						"debit": self.additional_interest_amount,
						"debit_in_account_currency": self.additional_interest_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.loan,
						"remarks": _("Interest accrued from {0} to {1} against loan: {2}").format(
							self.last_accrual_date, self.posting_date, self.loan
						),
						"cost_center": cost_center,
						"posting_date": self.accrual_date or self.posting_date,
					}
				)
			)

			gle_map.append(
				self.get_gl_dict(
					{
						"account": account_details.additional_interest_income,
						"against": income_account,
						"credit": self.additional_interest_amount,
						"credit_in_account_currency": self.additional_interest_amount,
						"against_voucher_type": "Loan",
						"against_voucher": self.loan,
						"remarks": ("Interest accrued from {0} to {1} against loan: {2}").format(
							self.last_accrual_date, self.posting_date, self.loan
						),
						"cost_center": cost_center,
						"posting_date": self.accrual_date or self.posting_date,
					}
				)
			)

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj, merge_entries=False)


# For Eg: If Loan disbursement date is '01-09-2019' and disbursed amount is 1000000 and
# rate of interest is 13.5 then first loan interest accrual will be on '01-10-2019'
# which means interest will be accrued for 30 days which should be equal to 11095.89
def calculate_accrual_amount_for_loans(
	loan,
	posting_date,
	process_loan_interest=None,
	accrual_type=None,
	is_future_accrual=0,
	accrual_date=None,
	loan_disbursement=None,
):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import (
		get_pending_principal_amount,
	)

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	total_payable_interest = 0

	last_accrual_date = get_last_accrual_date(
		loan.name, posting_date, "Normal Interest", loan_disbursement=loan_disbursement
	)
	if loan.is_term_loan:
		overlapping_dates = get_overlapping_dates(
			loan.name, last_accrual_date, posting_date, loan_disbursement=loan_disbursement
		)
		for schedule in overlapping_dates:
			last_accrual_date_for_schedule = (
				get_last_accrual_date(
					loan.name,
					posting_date,
					"Normal Interest",
					loan_repayment_schedule=schedule.parent,
					is_future_accrual=is_future_accrual,
					loan_disbursement=loan_disbursement,
				)
				or last_accrual_date
			)

			pending_principal_amount = get_principal_amount_for_term_loan(
				schedule.parent, schedule.payment_date
			)

			payable_interest = get_interest_for_term(
				loan.company,
				loan.rate_of_interest,
				pending_principal_amount,
				last_accrual_date_for_schedule,
				schedule.payment_date,
			)

			if payable_interest > 0:
				total_payable_interest += payable_interest
				if not is_future_accrual:
					make_loan_interest_accrual_entry(
						loan.name,
						pending_principal_amount,
						flt(payable_interest, precision),
						process_loan_interest,
						last_accrual_date_for_schedule,
						schedule.payment_date,
						accrual_type,
						"Normal Interest",
						loan.rate_of_interest,
						loan_repayment_schedule=schedule.parent,
						accrual_date=accrual_date,
					)
			elif is_future_accrual:
				last_accrual_date = schedule.payment_date
	else:
		no_of_days = date_diff(posting_date or nowdate(), last_accrual_date)
		if no_of_days <= 0:
			return

		pending_principal_amount = get_pending_principal_amount(loan)

		payable_interest = get_interest_amount(
			no_of_days,
			principal_amount=pending_principal_amount,
			rate_of_interest=loan.rate_of_interest,
			company=loan.company,
			posting_date=posting_date,
		)

		if payable_interest > 0:
			make_loan_interest_accrual_entry(
				loan.name,
				pending_principal_amount,
				payable_interest,
				process_loan_interest,
				last_accrual_date,
				posting_date,
				accrual_type,
				"Normal Interest",
				loan.rate_of_interest,
			)

			create_loan_demand(loan.name, posting_date, "Normal", "Interest", payable_interest)
	if is_future_accrual:
		return total_payable_interest


def get_interest_for_term(company, rate_of_interest, pending_principal_amount, from_date, to_date):
	no_of_days = date_diff(to_date, from_date) + 1
	payable_interest = get_interest_amount(
		no_of_days,
		principal_amount=pending_principal_amount,
		rate_of_interest=rate_of_interest,
		company=company,
		posting_date=to_date,
	)

	return payable_interest


def make_loan_interest_accrual_entry(
	loan,
	base_amount,
	interest_amount,
	process_loan_interest,
	start_date,
	posting_date,
	accrual_type,
	interest_type,
	rate_of_interest,
	loan_demand=None,
	loan_repayment_schedule=None,
	additional_interest=0,
	accrual_date=None,
	loan_repayment_schedule_detail=None,
):
	precision = cint(frappe.db.get_default("currency_precision")) or 2
	if flt(interest_amount, precision) > 0:
		loan_interest_accrual = frappe.new_doc("Loan Interest Accrual")
		loan_interest_accrual.loan = loan
		loan_interest_accrual.interest_amount = flt(interest_amount, precision)
		loan_interest_accrual.base_amount = flt(base_amount, precision)
		loan_interest_accrual.posting_date = posting_date or nowdate()
		loan_interest_accrual.start_date = start_date
		loan_interest_accrual.process_loan_interest_accrual = process_loan_interest
		loan_interest_accrual.accrual_type = accrual_type
		loan_interest_accrual.interest_type = interest_type
		loan_interest_accrual.rate_of_interest = rate_of_interest
		loan_interest_accrual.loan_demand = loan_demand
		loan_interest_accrual.loan_repayment_schedule = loan_repayment_schedule
		loan_interest_accrual.additional_interest_amount = additional_interest
		loan_interest_accrual.accrual_date = accrual_date
		loan_interest_accrual.loan_repayment_schedule_detail = loan_repayment_schedule_detail

		loan_interest_accrual.save()
		loan_interest_accrual.submit()


def get_overlapping_dates(loan, last_accrual_date, posting_date, loan_disbursement=None):
	filters = {"loan": loan, "docstatus": 1, "status": "Active", "posting_date": ("<=", posting_date)}

	if loan_disbursement:
		filters["loan_disbursement"] = loan_disbursement

	schedules_details = frappe.db.get_all(
		"Loan Repayment Schedule",
		filters=filters,
		fields=["name", "maturity_date"],
	)

	schedules = [d.name for d in schedules_details]

	freeze_date = frappe.db.get_value("Loan", loan, "freeze_date")
	if freeze_date and getdate(freeze_date) < getdate(posting_date):
		posting_date = freeze_date

	schedule_filters = {
		"parent": ("in", schedules),
		"payment_date": ("between", [last_accrual_date, posting_date]),
	}

	if len(schedules) == 1:
		schedule_filters["parent"] = schedules[0]

	schedule_dates = (
		frappe.db.get_all(
			"Repayment Schedule",
			filters=schedule_filters,
			fields=["payment_date", "parent"],
			order_by="payment_date",
		)
		or []
	)

	for schedule_date in schedule_dates:
		schedule_date["payment_date"] = add_days(schedule_date.payment_date, -1)

	maturity_map = {}
	for schedule in schedules_details:
		to_accrual_date = posting_date
		maturity_date = schedule.get("maturity_date")
		maturity_map[schedule.name] = maturity_date
		if maturity_date and getdate(maturity_date) <= getdate(posting_date):
			to_accrual_date = add_days(maturity_date, -1)

		schedule_dates.append(frappe._dict({"payment_date": to_accrual_date, "parent": schedule.name}))

	for schedule_date in schedule_dates:
		maturity_date = maturity_map.get(schedule_date.parent)
		if maturity_date and getdate(schedule_date.payment_date) >= getdate(maturity_date):
			schedule_date["payment_date"] = add_days(maturity_date, -1)

	return schedule_dates


def get_principal_amount_for_term_loan(repayment_schedule, date):
	principal_amount = frappe.db.get_value(
		"Repayment Schedule",
		{"parent": repayment_schedule, "payment_date": ("<=", date)},
		"balance_loan_amount",
		order_by="payment_date DESC",
	)

	if not principal_amount:
		principal_amount = frappe.db.get_value(
			"Loan Repayment Schedule", repayment_schedule, "current_principal_amount", cache=True
		)

	return principal_amount


def get_term_loan_payment_date(loan_repayment_schedule, date):
	payment_date = frappe.db.get_value(
		"Repayment Schedule",
		{"parent": loan_repayment_schedule, "payment_date": ("<=", date)},
		"MAX(payment_date)",
	)

	return payment_date


def calculate_penal_interest_for_loans(
	loan,
	posting_date,
	process_loan_interest=None,
	accrual_type=None,
	is_future_accrual=0,
	accrual_date=None,
	loan_disbursement=None,
	via_background_job=False,
):
	from lending.loan_management.doctype.loan_repayment.loan_repayment import get_unpaid_demands

	precision = cint(frappe.db.get_default("currency_precision")) or 2

	loan_product, freeze_date, loan_status, penal_interest_rate = frappe.get_value(
		"Loan", loan.name, ["loan_product", "freeze_date", "status", "penalty_charges_rate"]
	)

	penal_interest_rate = frappe.db.get_value("Loan", loan.name, "penalty_charges_rate")

	if not penal_interest_rate:
		penal_interest_rate = frappe.get_value(
			"Loan Product", loan_product, "penalty_interest_rate", cache=True
		)

	if flt(penal_interest_rate, precision) <= 0:
		return

	demands = get_unpaid_demands(loan.name, posting_date, emi_wise=True)

	grace_period_days = cint(
		frappe.get_value("Loan Product", loan_product, "grace_period_in_days", cache=True)
	)
	total_penal_interest = 0

	if freeze_date and getdate(freeze_date) < getdate(posting_date):
		posting_date = freeze_date

	for demand in demands:
		penal_interest_amount = 0
		additional_interest = 0
		on_migrate = False

		if getdate(posting_date) >= add_days(demand.demand_date, grace_period_days):
			last_accrual_date = get_last_accrual_date(
				loan.name,
				posting_date,
				"Penal Interest",
				repayment_schedule_detail=demand.repayment_schedule_detail,
				loan_disbursement=loan_disbursement,
			)

			if not last_accrual_date:
				last_accrual_date = get_last_accrual_date(
					loan.name,
					posting_date,
					"Penal Interest",
					loan_repayment_schedule=demand.loan_repayment_schedule,
				)
				on_migrate = True

			if not last_accrual_date:
				from_date = demand.demand_date
			elif on_migrate:
				from_date = last_accrual_date
				if getdate(from_date) <= getdate(demand.demand_date):
					from_date = demand.demand_date
			else:
				from_date = add_days(last_accrual_date, 1)

			no_of_days = date_diff(posting_date, from_date)

			penal_interest_amount = flt(demand.pending_amount) * penal_interest_rate * no_of_days / 36500

			if flt(penal_interest_amount, precision) > 0:
				total_penal_interest += penal_interest_amount

				principal_amount = frappe.db.get_value(
					"Loan Demand",
					{
						"loan": loan.name,
						"repayment_schedule_detail": demand.repayment_schedule_detail,
						"demand_type": "EMI",
						"demand_subtype": "Principal",
					},
					"outstanding_amount",
				)

				if not principal_amount:
					continue

				per_day_interest = get_per_day_interest(
					principal_amount, loan.rate_of_interest, loan.company, posting_date
				)
				additional_interest = flt(per_day_interest * no_of_days, precision)

				if not is_future_accrual:
					if flt(penal_interest_amount, precision) > 0:
						make_loan_interest_accrual_entry(
							loan.name,
							demand.pending_amount,
							penal_interest_amount,
							process_loan_interest,
							from_date,
							posting_date,
							accrual_type,
							"Penal Interest",
							penal_interest_rate,
							loan_demand=demand.name,
							additional_interest=additional_interest,
							accrual_date=accrual_date,
							loan_repayment_schedule_detail=demand.repayment_schedule_detail,
						)

					if via_background_job:
						demand_date = add_days(posting_date, 1)
					else:
						demand_date = posting_date

					if loan_status != "Written Off":
						if penal_interest_amount - additional_interest > 0:
							create_loan_demand(
								loan.name,
								demand_date,
								"Penalty",
								"Penalty",
								penal_interest_amount - additional_interest,
								loan_repayment_schedule=demand.loan_repayment_schedule,
								loan_disbursement=demand.loan_disbursement,
							)

						if flt(additional_interest, precision) > 0:
							create_loan_demand(
								loan.name,
								demand_date,
								"Additional Interest",
								"Additional Interest",
								additional_interest,
								loan_repayment_schedule=demand.loan_repayment_schedule,
								loan_disbursement=demand.loan_disbursement,
							)

	if is_future_accrual:
		return total_penal_interest


def make_accrual_interest_entry_for_loans(
	posting_date,
	process_loan_interest=None,
	loan=None,
	loan_product=None,
	accrual_type="Regular",
	accrual_date=None,
	limit=0,
):

	loan_doc = frappe.qb.DocType("Loan")

	query = (
		frappe.qb.from_(loan_doc)
		.select(
			loan_doc.name,
			loan_doc.total_payment,
			loan_doc.total_amount_paid,
			loan_doc.debit_adjustment_amount,
			loan_doc.credit_adjustment_amount,
			loan_doc.refund_amount,
			loan_doc.loan_account,
			loan_doc.interest_income_account,
			loan_doc.penalty_income_account,
			loan_doc.loan_amount,
			loan_doc.is_term_loan,
			loan_doc.status,
			loan_doc.disbursement_date,
			loan_doc.disbursed_amount,
			loan_doc.applicant_type,
			loan_doc.applicant,
			loan_doc.rate_of_interest,
			loan_doc.total_interest_payable,
			loan_doc.written_off_amount,
			loan_doc.total_principal_paid,
			loan_doc.repayment_start_date,
			loan_doc.company,
		)
		.where(loan_doc.docstatus == 1)
		.where(loan_doc.status.isin(["Disbursed", "Partially Disbursed", "Active", "Written Off"]))
		.where(
			(loan_doc.excess_amount_paid <= 0) | (loan_doc.repayment_schedule_type == "Line of Credit")
		)
		.where((loan_doc.loan_product.isnotnull()) & (loan_doc.loan_product != ""))
	)

	if loan:
		query = query.where(loan_doc.name == loan)

	if loan_product:
		query = query.where(loan_doc.loan_product == loan_product)

	if limit:
		query = query.limit(limit)

	open_loans = query.run(as_dict=1)

	if loan:
		process_interest_accrual_batch(
			open_loans, posting_date, process_loan_interest, accrual_type, accrual_date
		)
	else:
		BATCH_SIZE = 5000
		batch_list = list(get_batches(open_loans, BATCH_SIZE))
		for batch in batch_list:
			frappe.enqueue(
				process_interest_accrual_batch,
				loans=batch,
				posting_date=posting_date,
				process_loan_interest=process_loan_interest,
				accrual_type=accrual_type,
				accrual_date=accrual_date,
				via_background_job=True,
				queue="long",
				enqueue_after_commit=True,
			)


def get_batches(open_loans, batch_size):
	for i in range(0, len(open_loans), batch_size):
		yield open_loans[i : i + batch_size]


def process_interest_accrual_batch(
	loans, posting_date, process_loan_interest, accrual_type, accrual_date, via_background_job=False
):
	for loan in loans:
		try:
			calculate_penal_interest_for_loans(
				loan,
				posting_date,
				process_loan_interest=process_loan_interest,
				accrual_type=accrual_type,
				accrual_date=accrual_date,
				via_background_job=via_background_job,
			)
			calculate_accrual_amount_for_loans(
				loan,
				posting_date,
				process_loan_interest=process_loan_interest,
				accrual_type=accrual_type,
				accrual_date=accrual_date,
			)

			if len(loans) > 1:
				frappe.db.commit()
		except Exception as e:
			if len(loans) > 1:
				frappe.log_error(
					title="Loan Interest Accrual Error",
					message=frappe.get_traceback(),
					reference_doctype="Loan",
					reference_name=loan.name,
				)
				frappe.db.rollback()
			else:
				raise e


def get_last_accrual_date(
	loan,
	posting_date,
	interest_type,
	demand=None,
	loan_repayment_schedule=None,
	is_future_accrual=0,
	repayment_schedule_detail=None,
	loan_disbursement=None,
):
	filters = {"loan": loan, "docstatus": 1, "interest_type": interest_type}

	if demand:
		filters["loan_demand"] = demand

	if repayment_schedule_detail:
		filters["loan_repayment_schedule_detail"] = repayment_schedule_detail

	if loan_repayment_schedule:
		filters["loan_repayment_schedule"] = loan_repayment_schedule

	if is_future_accrual:
		filters["posting_date"] = ("<=", posting_date)

	last_interest_accrual_date = frappe.db.get_value(
		"Loan Interest Accrual", filters, "MAX(posting_date)", for_update=True
	)

	if loan_repayment_schedule:
		if last_interest_accrual_date:
			return add_days(last_interest_accrual_date, 1)
		else:
			dates = frappe.db.get_value(
				"Loan Repayment Schedule",
				loan_repayment_schedule,
				["moratorium_end_date", "posting_date", "moratorium_type"],
				as_dict=1,
			)

			if dates.moratorium_type == "EMI" and dates.moratorium_end_date:
				final_date = dates.moratorium_end_date
			else:
				final_date = dates.posting_date

			return final_date

	last_disbursement_date = get_last_disbursement_date(
		loan, posting_date, loan_disbursement=loan_disbursement
	)

	if interest_type == "Penal Interest":
		return last_interest_accrual_date

	if last_interest_accrual_date:
		# interest for last interest accrual date is already booked, so add 1 day
		last_interest_accrual_date = add_days(last_interest_accrual_date, 1)

		if last_disbursement_date and getdate(last_disbursement_date) > getdate(
			last_interest_accrual_date
		):
			last_interest_accrual_date = add_days(last_disbursement_date, -1)

		return last_interest_accrual_date
	else:
		moratorium_details = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan, "docstatus": 1, "status": "Active"},
			["moratorium_end_date", "moratorium_type"],
			as_dict=1,
		)

		if (
			moratorium_details
			and moratorium_details.moratorium_end_date
			and moratorium_details.moratorium_type == "EMI"
			and getdate(moratorium_details.moratorium_end_date) > getdate(last_disbursement_date)
		):
			last_interest_accrual_date = add_days(moratorium_details.moratorium_end_date, 1)
		else:
			last_interest_accrual_date = add_days(last_disbursement_date, -1)

		return last_interest_accrual_date


def get_last_disbursement_date(loan, posting_date, loan_disbursement=None):
	schedule_type = frappe.db.get_value("Loan", loan, "repayment_schedule_type", cache=True)

	if schedule_type == "Line of Credit":
		field = "MIN(posting_date)"
	else:
		field = "MAX(disbursement_date)"

	filters = {"docstatus": 1, "against_loan": loan, "posting_date": ("<=", posting_date)}

	if loan_disbursement:
		filters["name"] = loan_disbursement

	last_disbursement_date = frappe.db.get_value(
		"Loan Disbursement",
		filters,
		field,
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


def reverse_loan_interest_accruals(
	loan,
	posting_date,
	interest_type=None,
	loan_repayment_schedule=None,
	is_npa=0,
	on_payment_allocation=False,
	loan_disbursement=None,
	future_accruals=False,
):
	from lending.loan_management.doctype.loan_write_off.loan_write_off import (
		write_off_suspense_entries,
	)

	filters = {
		"loan": loan,
		"posting_date": (">=", posting_date),
		"docstatus": 1,
	}

	or_filters = {}

	if interest_type:
		filters["interest_type"] = interest_type

	if interest_type == "Penal Interest":
		filters["interest_type"] = ("in", ["Penal Interest", "Additional Interest"])

	if loan_repayment_schedule and not future_accruals:
		filters["loan_repayment_schedule"] = loan_repayment_schedule
	elif loan_repayment_schedule and future_accruals:
		or_filters["loan_repayment_schedule"] = loan_repayment_schedule
		or_filters["posting_date"] = (">", posting_date)

	if loan_disbursement:
		filters["loan_disbursement"] = loan_disbursement

	accruals = (
		frappe.get_all("Loan Interest Accrual", filters=filters, fields=["name", "posting_date"]) or []
	)

	for accrual in accruals:
		accrual_doc = frappe.get_doc("Loan Interest Accrual", accrual.name, for_update=True)
		if accrual_doc.docstatus == 1:
			accrual_doc.flags.ignore_links = True
			accrual_doc.cancel()

		if is_npa:
			interest_amount = 0
			penalty_amount = 0
			additional_interest_amount = 0

			if interest_type == "Normal Interest":
				interest_amount = accrual_doc.interest_amount
			elif interest_type == "Penal Interest":
				penalty_amount = accrual_doc.interest_amount - accrual_doc.additional_interest_amount
				additional_interest_amount = accrual_doc.additional_interest_amount

			write_off_suspense_entries(
				loan,
				accrual_doc.loan_product,
				posting_date,
				accrual_doc.company,
				interest_amount=interest_amount,
				penalty_amount=penalty_amount,
				additional_interest_amount=additional_interest_amount,
				on_payment_allocation=on_payment_allocation,
			)

	return accruals
