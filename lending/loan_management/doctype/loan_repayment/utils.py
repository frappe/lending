import frappe
from frappe.utils import add_days, cint, flt


def get_pending_principal_amount_for_loans(loans, disbursement_map):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	principal_amount_map = {}

	loan_list = [loan.name for loan in loans]
	disbursement_details = frappe._dict(
		frappe.db.get_all(
			"Loan Disbursement",
			{"against_loan": ["in", loan_list]},
			["name", "sum(disbursed_amount - principal_amount_paid) as pending_principal_amount"],
			as_list=1,
		)
	)

	for loan in loans:
		if loan.repayment_schedule_type == "Line of Credit":
			for disbursement in disbursement_map.get(loan.name, []):
				principal_amount_map[(loan.name, disbursement)] = disbursement_details.get(disbursement, 0)
		elif loan.status == "Cancelled":
			pending_principal_amount = 0
			principal_amount_map[loan.name] = pending_principal_amount
		elif loan.status in ("Disbursed", "Closed", "Active", "Written Off"):
			pending_principal_amount = flt(
				flt(loan.total_payment)
				+ flt(loan.debit_adjustment_amount)
				- flt(loan.credit_adjustment_amount)
				- flt(loan.total_principal_paid)
				- flt(loan.total_interest_payable),
				precision,
			)
			principal_amount_map[loan.name] = pending_principal_amount

		else:
			pending_principal_amount = flt(
				flt(loan.disbursed_amount)
				+ flt(loan.debit_adjustment_amount)
				- flt(loan.credit_adjustment_amount)
				- flt(loan.total_principal_paid),
				precision,
			)

			principal_amount_map[loan.name] = pending_principal_amount

	return principal_amount_map


def get_disbursement_map(loans):
	loans = [loan.name for loan in loans]
	disbursements = frappe.db.get_all(
		"Loan Repayment Schedule",
		{"loan": ["in", loans], "status": "Active"},
		["loan", "loan_disbursement"],
	)

	disbursement_map = {}
	for disbursement in disbursements:
		disbursement_map.setdefault(disbursement.loan, []).append(disbursement.loan_disbursement)

	return disbursement_map


def process_amount_for_bulk_loans(
	loan, demands, disbursement, pending_principal_amount, unbooked_interest, amounts
):

	precision = cint(frappe.db.get_default("currency_precision")) or 2
	total_pending_interest = 0
	charges = 0
	penalty_amount = 0
	payable_principal_amount = 0

	for demand in demands:
		if demand.demand_subtype == "Interest":
			total_pending_interest += demand.outstanding_amount
		elif demand.demand_subtype == "Principal":
			payable_principal_amount += demand.outstanding_amount
		elif demand.demand_subtype in ("Penalty", "Additional Interest"):
			penalty_amount += demand.outstanding_amount
		elif demand.demand_type == "Charges":
			charges += demand.outstanding_amount

	amounts["loan"] = loan.name
	amounts["loan_disbursement"] = disbursement
	amounts["total_charges_payable"] = charges
	amounts["pending_principal_amount"] = flt(pending_principal_amount, precision)
	amounts["payable_principal_amount"] = flt(payable_principal_amount, precision)
	amounts["interest_amount"] = flt(total_pending_interest, precision)
	amounts["penalty_amount"] = flt(penalty_amount, precision)
	amounts["payable_amount"] = flt(
		payable_principal_amount + total_pending_interest + penalty_amount + charges, precision
	)
	amounts["unbooked_interest"] = flt(unbooked_interest, precision)
	amounts["written_off_amount"] = flt(loan.written_off_amount, precision)
	amounts["unpaid_demands"] = demands
	amounts["excess_amount_paid"] = flt(loan.excess_amount_paid, precision)

	return amounts


def get_unbooked_interest_for_loans(
	loans, posting_date, interest_type="Normal Interest", last_demand_date=None
):

	loan_list = [loan.name for loan in loans]
	loan_type_map = {loan.name: loan.repayment_schedule_type for loan in loans}

	filters = {
		"loan": ("in", loan_list),
		"docstatus": 1,
		"posting_date": ("<=", posting_date),
		"interest_type": interest_type,
	}

	if last_demand_date:
		filters["posting_date"] = (">", last_demand_date)

	accrued_interests = frappe.db.get_all(
		"Loan Interest Accrual",
		filters,
		["loan", "loan_disbursement", "SUM(interest_amount) as unbooked_interest"],
		group_by="loan, loan_disbursement",
	)

	accrued_interest_map = {}

	for accrued_interest in accrued_interests:
		if loan_type_map.get(accrued_interest.loan) == "Line of Credit":
			accrued_interest_map[
				(accrued_interest.loan, accrued_interest.loan_disbursement)
			] = accrued_interest.unbooked_interest
		else:
			accrued_interest_map.setdefault(accrued_interest.loan, 0)
			accrued_interest_map[accrued_interest.loan] += accrued_interest.unbooked_interest

	return accrued_interest_map


def get_last_demand_date(posting_date, demand_subtype="Interest", loan=None):
	filters = {
		"docstatus": 1,
		"demand_subtype": demand_subtype,
		"demand_date": ("<=", posting_date),
	}

	if loan:
		filters["loan"] = loan

	last_demand_date = frappe.db.get_value(
		"Loan Demand",
		filters,
		"MAX(demand_date)",
	)

	if demand_subtype == "Interest" and last_demand_date:
		last_demand_date = add_days(last_demand_date, -1)

	return last_demand_date


def get_latest_accrual_date(posting_date, interest_type="Interest"):
	filters = {
		"docstatus": 1,
		"interest_type": interest_type,
		"posting_date": (">", posting_date),
	}

	latest_accrual_date = frappe.db.get_value(
		"Loan Interest Accrual",
		filters,
		"MAX(posting_date)",
	)

	return latest_accrual_date
