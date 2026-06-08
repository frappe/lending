# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Coalesce


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"label": _("Loan Account"),
			"fieldname": "loan_account",
			"fieldtype": "Link",
			"options": "Loan",
			"width": 180,
		},
		{
			"label": _("Loan Disbursement ID"),
			"fieldname": "loan_disbursement_id",
			"fieldtype": "Link",
			"options": "Loan Disbursement",
			"width": 180,
		},
		{
			"label": _("Applicant"),
			"fieldname": "applicant",
			"fieldtype": "Dynamic Link",
			"options": "applicant_type",
			"width": 150,
		},
		{
			"label": _("Applicant Type"),
			"fieldname": "applicant_type",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Tranche Number"),
			"fieldname": "tranche_number",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("Interest Rate"),
			"fieldname": "interest_rate",
			"fieldtype": "Percent",
			"width": 120,
		},
		{
			"label": _("Maturity Date"),
			"fieldname": "maturity_date",
			"fieldtype": "Date",
			"width": 130,
		},
		{
			"label": _("Disbursement Date"),
			"fieldname": "disbursement_date",
			"fieldtype": "Date",
			"width": 130,
		},
		{
			"label": _("Disbursed Amount"),
			"fieldname": "disbursed_amount",
			"fieldtype": "Currency",
			"width": 140,
		},
		{
			"label": _("Charge Type"),
			"fieldname": "charge_type",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Charge Amount"),
			"fieldname": "charge_amount",
			"fieldtype": "Currency",
			"width": 140,
		},
	]


def get_data(filters):
	LoanDisbursement = DocType("Loan Disbursement")
	Loan = DocType("Loan")
	LoanDisbursementCharge = DocType("Loan Disbursement Charge")
	LoanRepaymentSchedule = DocType("Loan Repayment Schedule")

	# Subquery to get maturity date from repayment schedule
	maturity_date_subquery = (
		frappe.qb.from_(LoanRepaymentSchedule)
		.select(LoanRepaymentSchedule.maturity_date)
		.where(LoanRepaymentSchedule.loan_disbursement == LoanDisbursement.name)
		.where(LoanRepaymentSchedule.docstatus == 1)
		.where(LoanRepaymentSchedule.status.isin(["Active", "Closed"]))
		.limit(1)
	)

	query = (
		frappe.qb.from_(LoanDisbursement)
		.left_join(Loan)
		.on(LoanDisbursement.against_loan == Loan.name)
		.left_join(LoanDisbursementCharge)
		.on(LoanDisbursementCharge.parent == LoanDisbursement.name)
		.select(
			Loan.name.as_("loan_account"),
			LoanDisbursement.name.as_("loan_disbursement_id"),
			Loan.applicant.as_("applicant"),
			Loan.applicant_type.as_("applicant_type"),
			LoanDisbursement.tranche_number.as_("tranche_number"),
			Loan.rate_of_interest.as_("interest_rate"),
			maturity_date_subquery.as_("maturity_date"),
			LoanDisbursement.disbursement_date.as_("disbursement_date"),
			LoanDisbursement.disbursed_amount.as_("disbursed_amount"),
			Coalesce(LoanDisbursementCharge.charge, "").as_("charge_type"),
			Coalesce(LoanDisbursementCharge.amount, 0).as_("charge_amount"),
		)
		.where(LoanDisbursement.docstatus == 1)
	)

	if filters.get("company"):
		query = query.where(LoanDisbursement.company == filters.get("company"))
	if filters.get("applicant_type"):
		query = query.where(Loan.applicant_type == filters.get("applicant_type"))
	if filters.get("applicant"):
		query = query.where(Loan.applicant == filters.get("applicant"))
	if filters.get("loan_product"):
		query = query.where(Loan.loan_product == filters.get("loan_product"))
	if filters.get("loan"):
		query = query.where(Loan.name == filters.get("loan"))
	if filters.get("loan_disbursement"):
		query = query.where(LoanDisbursement.name == filters.get("loan_disbursement"))

	query = query.orderby(
		LoanDisbursement.against_loan,
		LoanDisbursement.disbursement_date,
		LoanDisbursement.tranche_number,
		LoanDisbursement.creation,
	)

	return query.run(as_dict=True)
