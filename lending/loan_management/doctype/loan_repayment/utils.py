import frappe
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import cint, flt


def get_pending_principal_amount_for_loans(loans, disbursement_map, consolidated=False):
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	principal_amount_map = {}

	loan_list = [loan.name for loan in loans]
	loan_disbursement = DocType("Loan Disbursement")
	disbursement_details = frappe._dict(
		frappe.qb.from_(loan_disbursement)
		.select(
			loan_disbursement.name,
			(loan_disbursement.disbursed_amount - loan_disbursement.principal_amount_paid).as_(
				"pending_principal_amount"
			),
		)
		.where(loan_disbursement.against_loan.isin(loan_list))
		.run(as_list=1)
	)
	for loan in loans:
		if loan.repayment_schedule_type == "Line of Credit" and not consolidated:
			for disbursement in disbursement_map.get(loan.name, []):
				principal_amount_map[(loan.name, disbursement)] = disbursement_details[disbursement]
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


def get_last_demand_date_map(loans, posting_date, demand_subtype="Interest"):
	"""Return {loan: MAX(demand_date)} for all loans in a single grouped query.

	Bulk equivalent of get_last_demand_date(), used to avoid an N+1 query in
	the get_bulk_due_details loop. Loans with no matching demand are absent from
	the map (callers should treat that as None, same as the per-loan function).
	"""
	if not loans:
		return {}

	LoanDemand = DocType("Loan Demand")
	rows = (
		frappe.qb.from_(LoanDemand)
		.select(LoanDemand.loan, fn.Max(LoanDemand.demand_date))
		.where(
			(LoanDemand.docstatus == 1)
			& (LoanDemand.demand_subtype == demand_subtype)
			& (LoanDemand.demand_date <= posting_date)
			& (LoanDemand.loan.isin(loans))
		)
		.groupby(LoanDemand.loan)
	).run()

	return {row[0]: row[1] for row in rows}


def process_amount_for_bulk_loans(
	loan,
	demands,
	loan_disbursement,
	pending_principal_amount,
	unbooked_interest,
	amounts,
	posting_date,
	available_security_deposit_map,
	last_demand_date,
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
	amounts["loan_disbursement"] = loan_disbursement
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
	amounts["due_date"] = last_demand_date
	amounts["excess_amount_paid"] = flt(loan.excess_amount_paid, precision)
	amounts["available_security_deposit"] = available_security_deposit_map[loan.name]

	return amounts


def get_last_demand_date(posting_date, demand_subtype="Interest", loan=None):
	LoanDemand = DocType("Loan Demand")

	query = (
		frappe.qb.from_(LoanDemand)
		.select(fn.Max(LoanDemand.demand_date))
		.where(
			(LoanDemand.docstatus == 1)
			& (LoanDemand.demand_subtype == demand_subtype)
			& (LoanDemand.demand_date <= posting_date)
		)
	)

	if loan:
		query = query.where(LoanDemand.loan == loan)

	last_demand_date = query.run()[0][0]

	return last_demand_date


def get_latest_accrual_date(posting_date, interest_type="Interest"):
	LoanInterestAccrual = DocType("Loan Interest Accrual")

	query = (
		frappe.qb.from_(LoanInterestAccrual)
		.select(fn.Max(LoanInterestAccrual.posting_date))
		.where(
			(LoanInterestAccrual.docstatus == 1)
			& (LoanInterestAccrual.interest_type == interest_type)
			& (LoanInterestAccrual.posting_date > posting_date)
		)
	)

	latest_accrual_date = query.run()[0][0]

	return latest_accrual_date
