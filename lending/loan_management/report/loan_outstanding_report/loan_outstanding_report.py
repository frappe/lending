from pypika import functions as fn

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import flt, getdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters or {})
	return columns, data


def get_columns():
	return [
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan"},
		{
			"label": _("Loan Disbursement"),
			"fieldname": "loan_disbursement",
			"fieldtype": "Link",
			"options": "Loan Disbursement",
		},
		{"label": _("Disbursement Date"), "fieldname": "disbursement_date", "fieldtype": "Date"},
		{"label": _("Disbursed Amount"), "fieldname": "disbursed_amount", "fieldtype": "Currency"},
		{"label": _("Applicant Name"), "fieldname": "applicant", "fieldtype": "Data"},
		{
			"label": _("Loan Product"),
			"fieldname": "loan_product",
			"fieldtype": "Link",
			"options": "Loan Product",
		},
		{"label": _("Loan Date"), "fieldname": "posting_date", "fieldtype": "Date"},
		{"label": _("Loan Amount"), "fieldname": "loan_amount", "fieldtype": "Currency"},
		{
			"label": _("Total Principal Paid"),
			"fieldname": "principal_amount_paid",
			"fieldtype": "Currency",
		},
		{"label": _("Total Interest Paid"), "fieldname": "total_interest_paid", "fieldtype": "Currency"},
		{"label": _("Total Amount Paid"), "fieldname": "total_amount_paid", "fieldtype": "Currency"},
		{
			"label": _("Principal Outstanding"),
			"fieldname": "pending_principal_amount",
			"fieldtype": "Currency",
		},
		{"label": _("Principal Overdue"), "fieldname": "principal_overdue", "fieldtype": "Currency"},
		{"label": _("Interest Overdue"), "fieldname": "interest_overdue", "fieldtype": "Currency"},
		{"label": _("Loan Status"), "fieldname": "status", "fieldtype": "Data"},
		{"label": _("EMIs Paid"), "fieldname": "total_installments_paid", "fieldtype": "Int"},
		{"label": _("EMIs Raised"), "fieldname": "total_installments_raised", "fieldtype": "Int"},
		{"label": _("EMIs Due"), "fieldname": "total_installments_overdue", "fieldtype": "Int"},
		{"label": _("Interest Rate (%)"), "fieldname": "rate_of_interest", "fieldtype": "Percent"},
	]


def get_data(filters):
	Loan = DocType("Loan")
	LoanDisb = DocType("Loan Disbursement")

	query = (
		frappe.qb.from_(LoanDisb)
		.inner_join(Loan)
		.on(Loan.name == LoanDisb.against_loan)
		.select(
			LoanDisb.name.as_("loan_disbursement"),
			LoanDisb.disbursement_date,
			LoanDisb.disbursed_amount,
			Loan.name.as_("loan"),
			Loan.applicant,
			Loan.loan_product,
			Loan.posting_date,
			Loan.loan_amount,
			Loan.status,
			Loan.rate_of_interest,
			Loan.repayment_schedule_type,
		)
		.where(Loan.docstatus == 1)
	)

	for fl in ("company", "applicant_type", "loan_product", "applicant", "loan"):
		if filters.get(fl):
			query = query.where(getattr(Loan, fl if fl != "loan" else "name") == filters[fl])

	if filters.get("loan_disbursement"):
		query = query.where(LoanDisb.name == filters["loan_disbursement"])

	disbursements = query.run(as_dict=True)
	results = []

	for row in disbursements:
		loan = row["loan"]
		loan_disbursement = row["loan_disbursement"]

		repayment = get_repayment_details(
			loan=loan,
			disbursement_name=loan_disbursement,
			repayment_schedule_type=row.get("repayment_schedule_type"),
		)
		emi = get_emi_details(loan_disbursement)

		principal_amount_paid = flt(repayment.get("principal_amount_paid"))
		total_interest_paid = flt(repayment.get("total_interest_paid"))
		total_amount_paid = flt(repayment.get("total_amount_paid"))

		amounts = calculate_amounts(
			against_loan=loan, posting_date=getdate(), loan_disbursement=loan_disbursement
		)
		pending_principal_amount = flt(amounts.get("pending_principal_amount", 0))
		principal_overdue = flt(amounts.get("payable_principal_amount", 0))
		interest_overdue = flt(amounts.get("interest_amount", 0))

		results.append(
			{
				**row,
				"principal_amount_paid": principal_amount_paid,
				"total_interest_paid": total_interest_paid,
				"total_amount_paid": total_amount_paid,
				"pending_principal_amount": pending_principal_amount,
				"principal_overdue": principal_overdue,
				"interest_overdue": interest_overdue,
				"repayment_period": emi.get("repayment_period"),
				"total_installments_paid": emi.get("total_installments_paid"),
				"total_installments_raised": emi.get("total_installments_raised"),
				"total_installments_overdue": emi.get("total_installments_overdue"),
			}
		)

	return results


def get_repayment_details(loan, disbursement_name=None, repayment_schedule_type=None):
	Repayment = DocType("Loan Repayment")
	condition = (Repayment.against_loan == loan) & (Repayment.docstatus == 1)

	if repayment_schedule_type == "Line of Credit" and disbursement_name:
		condition &= Repayment.loan_disbursement == disbursement_name
	else:
		condition &= Repayment.loan_disbursement.isnull() | (
			Repayment.loan_disbursement == disbursement_name
		)

	query = (
		frappe.qb.from_(Repayment)
		.select(
			fn.Sum(Repayment.principal_amount_paid).as_("principal_amount_paid"),
			fn.Sum(Repayment.total_interest_paid).as_("total_interest_paid"),
			fn.Sum(Repayment.amount_paid).as_("total_amount_paid"),
		)
		.where(condition)
	)

	result = query.run(as_dict=True)

	print("Query Result:", result)

	return (
		result[0]
		if result
		else {"principal_amount_paid": 0, "total_interest_paid": 0, "total_amount_paid": 0}
	)


def get_emi_details(disbursement_name):
	RepaymentSchedule = DocType("Loan Repayment Schedule")

	q = (
		frappe.qb.from_(RepaymentSchedule)
		.select(
			fn.Sum(RepaymentSchedule.total_installments_paid).as_("total_installments_paid"),
			fn.Sum(RepaymentSchedule.total_installments_raised).as_("total_installments_raised"),
			fn.Sum(RepaymentSchedule.total_installments_overdue).as_("total_installments_overdue"),
			fn.Sum(RepaymentSchedule.repayment_periods).as_("repayment_period"),
		)
		.where(
			(RepaymentSchedule.loan_disbursement == disbursement_name)
			& (RepaymentSchedule.docstatus == 1)
			& (RepaymentSchedule.status == "Active")
		)
	)

	res = q.run(as_dict=True)
	return res[0] if res else {}
