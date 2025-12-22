import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import flt


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart_data(data)

	return columns, data, None, chart


def get_chart_data(data):
	total_principal_outstanding = sum(row.get("pending_principal_amount", 0) for row in data)
	total_principal_overdue = sum(row.get("principal_overdue", 0) for row in data)
	total_interest_overdue = sum(row.get("interest_overdue", 0) for row in data)

	chart = {
		"data": {
			"labels": ["Total Principal Outstanding", "Total Principal Overdue", "Total Interest Overdue"],
			"datasets": [
				{
					"name": _("Amounts"),
					"values": [total_principal_outstanding, total_principal_overdue, total_interest_overdue],
				},
			],
		},
		"type": "donut",
		"colors": ["#fc4f51", "#78d6ff", "#7575ff"],
	}
	return chart


def get_columns():
	return [
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 200},
		{"label": _("Applicant Name"), "fieldname": "applicant", "fieldtype": "Data", "width": 150},
		{"label": _("Loan Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
		{"label": _("Loan Amount"), "fieldname": "loan_amount", "fieldtype": "Currency", "width": 130},
		{
			"label": _("Loan Disbursement"),
			"fieldname": "loan_disbursement",
			"fieldtype": "Link",
			"options": "Loan Disbursement",
			"width": 150,
		},
		{
			"label": _("Disbursement Date"),
			"fieldname": "disbursement_date",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("Disbursed Amount"),
			"fieldname": "disbursed_amount",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Loan Product"),
			"fieldname": "loan_product",
			"fieldtype": "Link",
			"options": "Loan Product",
			"width": 150,
		},
		{
			"label": _("Total Principal Paid"),
			"fieldname": "principal_amount_paid",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Total Interest Paid"),
			"fieldname": "total_interest_paid",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Total Amount Paid"),
			"fieldname": "total_amount_paid",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Principal Outstanding"),
			"fieldname": "pending_principal_amount",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Principal Overdue"),
			"fieldname": "principal_overdue",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Interest Overdue"),
			"fieldname": "interest_overdue",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("EMIs Paid"),
			"fieldname": "total_installments_paid",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("EMIs Raised"),
			"fieldname": "total_installments_raised",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("Installments Overdue"),
			"fieldname": "total_installments_overdue",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("Tenure"),
			"fieldname": "repayment_period",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Days Past Due"),
			"fieldname": "days_past_due",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("Interest Rate (%)"),
			"fieldname": "rate_of_interest",
			"fieldtype": "Percent",
			"width": 120,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	Loan = DocType("Loan")
	LoanDisbursement = DocType("Loan Disbursement")

	loan_disbursement_query = (
		frappe.qb.from_(LoanDisbursement)
		.inner_join(Loan)
		.on(Loan.name == LoanDisbursement.against_loan)
		.select(
			LoanDisbursement.name.as_("loan_disbursement"),
			LoanDisbursement.disbursement_date,
			LoanDisbursement.disbursed_amount,
			LoanDisbursement.principal_amount_paid.as_("disbursement_principal_paid"),
			Loan.name.as_("loan"),
			Loan.applicant,
			Loan.loan_product,
			Loan.posting_date,
			Loan.loan_amount,
			Loan.status,
			Loan.rate_of_interest,
			Loan.repayment_schedule_type,
			Loan.days_past_due,
			Loan.total_payment,
			Loan.debit_adjustment_amount,
			Loan.credit_adjustment_amount,
			Loan.total_principal_paid,
			Loan.total_interest_payable,
			Loan.disbursed_amount.as_("loan_disbursed_amount"),
		)
		.where((Loan.docstatus == 1) & (Loan.status != "Closed"))
	)

	if filters.get("company"):
		loan_disbursement_query = loan_disbursement_query.where(Loan.company == filters["company"])
	if filters.get("applicant_type"):
		loan_disbursement_query = loan_disbursement_query.where(
			Loan.applicant_type == filters["applicant_type"]
		)
	if filters.get("loan_product"):
		loan_disbursement_query = loan_disbursement_query.where(
			Loan.loan_product == filters["loan_product"]
		)
	if filters.get("applicant"):
		loan_disbursement_query = loan_disbursement_query.where(Loan.applicant == filters["applicant"])
	if filters.get("loan"):
		loan_disbursement_query = loan_disbursement_query.where(Loan.name == filters["loan"])
	if filters.get("loan_disbursement"):
		loan_disbursement_query = loan_disbursement_query.where(
			LoanDisbursement.name == filters["loan_disbursement"]
		)

	disbursement_records = loan_disbursement_query.run(as_dict=True)
	if not disbursement_records:
		return []

	loan_disbursement_keys = [(r["loan"], r["loan_disbursement"]) for r in disbursement_records]
	disbursement_names = [r["loan_disbursement"] for r in disbursement_records]
	repayment_type_by_loan = {
		r["loan"]: r.get("repayment_schedule_type") for r in disbursement_records
	}

	principal_overdue_map, interest_overdue_map = get_overdues_for_loans(loan_disbursement_keys)
	repayment_summary_map = get_bulk_repayment_details(loan_disbursement_keys, repayment_type_by_loan)
	emi_summary_map = get_bulk_emi_details(disbursement_names)

	report_rows = []
	for record in disbursement_records:
		loan = record["loan"]
		disb = record["loan_disbursement"]

		repayment_summary = repayment_summary_map.get((loan, disb), {})
		emi_summary = emi_summary_map.get(disb, {})

		if record.repayment_schedule_type == "Line of Credit" and disb:
			pending_principal = flt(record.disbursed_amount) - flt(record.disbursement_principal_paid)
		elif (
			record.status in ("Disbursed", "Closed", "Active", "Written Off", "Settled")
			and record.repayment_schedule_type != "Line of Credit"
		):
			pending_principal = (
				flt(record.total_payment)
				+ flt(record.debit_adjustment_amount)
				- flt(record.credit_adjustment_amount)
				- flt(record.total_principal_paid)
				- flt(record.total_interest_payable)
			)
		else:
			pending_principal = (
				flt(record.loan_disbursed_amount)
				+ flt(record.debit_adjustment_amount)
				- flt(record.credit_adjustment_amount)
				- flt(record.total_principal_paid)
			)

		report_rows.append(
			{
				**record,
				"principal_amount_paid": repayment_summary.get("principal_amount_paid", 0),
				"total_interest_paid": repayment_summary.get("total_interest_paid", 0),
				"total_amount_paid": repayment_summary.get("total_amount_paid", 0),
				"pending_principal_amount": pending_principal,
				"principal_overdue": principal_overdue_map.get((loan, disb), 0),
				"interest_overdue": interest_overdue_map.get((loan, disb), 0),
				"repayment_period": emi_summary.get("repayment_period"),
				"total_installments_paid": emi_summary.get("total_installments_paid"),
				"total_installments_raised": emi_summary.get("total_installments_raised"),
				"total_installments_overdue": emi_summary.get("total_installments_overdue"),
			}
		)

	return report_rows


def get_bulk_repayment_details(loan_disbursement_keys, repayment_type_by_loan):
	Repayment = DocType("Loan Repayment")
	loans = list({loan for loan, _ in loan_disbursement_keys})
	disbursements = list({disb for _, disb in loan_disbursement_keys})

	raw_repayment_data = (
		frappe.qb.from_(Repayment)
		.select(
			Repayment.against_loan.as_("loan"),
			Repayment.loan_disbursement.as_("loan_disbursement"),
			fn.Sum(Repayment.principal_amount_paid).as_("principal_amount_paid"),
			fn.Sum(Repayment.total_interest_paid).as_("total_interest_paid"),
			fn.Sum(Repayment.amount_paid).as_("total_amount_paid"),
		)
		.where(
			(Repayment.docstatus == 1)
			& (Repayment.against_loan.isin(loans))
			& ((Repayment.loan_disbursement.isin(disbursements)) | (Repayment.loan_disbursement.isnull()))
		)
		.groupby(Repayment.against_loan, Repayment.loan_disbursement)
	).run(as_dict=True)

	repayment_by_disbursement = {}
	repayment_by_loan = {}

	for row in raw_repayment_data:
		loan = row.get("loan")
		disb = row.get("loan_disbursement")
		repayment_totals = {
			"principal_amount_paid": flt(row.get("principal_amount_paid")),
			"total_interest_paid": flt(row.get("total_interest_paid")),
			"total_amount_paid": flt(row.get("total_amount_paid")),
		}
		if not disb:
			repayment_by_loan[loan] = repayment_totals
		else:
			repayment_by_disbursement[(loan, disb)] = repayment_totals

	repayment_summary_map = {}
	empty_totals = {
		"principal_amount_paid": 0.0,
		"total_interest_paid": 0.0,
		"total_amount_paid": 0.0,
	}

	for loan, disb in loan_disbursement_keys:
		disbursement_totals = repayment_by_disbursement.get((loan, disb), empty_totals)
		loan_totals = repayment_by_loan.get(loan, empty_totals)

		if repayment_type_by_loan.get(loan) == "Line of Credit":
			combined_totals = disbursement_totals
		else:
			combined_totals = {
				"principal_amount_paid": flt(disbursement_totals["principal_amount_paid"])
				+ flt(loan_totals["principal_amount_paid"]),
				"total_interest_paid": flt(disbursement_totals["total_interest_paid"])
				+ flt(loan_totals["total_interest_paid"]),
				"total_amount_paid": flt(disbursement_totals["total_amount_paid"])
				+ flt(loan_totals["total_amount_paid"]),
			}

		repayment_summary_map[(loan, disb)] = combined_totals

	return repayment_summary_map


def get_bulk_emi_details(disbursement_names):
	RepaymentSchedule = DocType("Loan Repayment Schedule")
	raw_emi_data = (
		frappe.qb.from_(RepaymentSchedule)
		.select(
			RepaymentSchedule.loan_disbursement,
			fn.Sum(RepaymentSchedule.total_installments_paid).as_("total_installments_paid"),
			fn.Sum(RepaymentSchedule.total_installments_raised).as_("total_installments_raised"),
			fn.Sum(RepaymentSchedule.total_installments_overdue).as_("total_installments_overdue"),
			fn.Sum(RepaymentSchedule.repayment_periods).as_("repayment_period"),
		)
		.where(
			(RepaymentSchedule.loan_disbursement.isin(disbursement_names))
			& (RepaymentSchedule.docstatus == 1)
			& (RepaymentSchedule.status == "Active")
		)
		.groupby(RepaymentSchedule.loan_disbursement)
	).run(as_dict=True)

	emi_summary_map = {}
	for row in raw_emi_data:
		emi_summary_map[row["loan_disbursement"]] = {
			"total_installments_paid": flt(row.get("total_installments_paid")),
			"total_installments_raised": flt(row.get("total_installments_raised")),
			"total_installments_overdue": flt(row.get("total_installments_overdue")),
			"repayment_period": flt(row.get("repayment_period")),
		}
	return emi_summary_map


def get_overdues_for_loans(loan_disbursement_keys):
	LoanDemand = DocType("Loan Demand")
	disbursement_names = [disb for _, disb in loan_disbursement_keys]

	raw_demand_data = (
		frappe.qb.from_(LoanDemand)
		.select(
			LoanDemand.loan.as_("loan"),
			LoanDemand.loan_disbursement.as_("loan_disbursement"),
			LoanDemand.demand_subtype,
			fn.Sum(LoanDemand.outstanding_amount).as_("outstanding"),
		)
		.where((LoanDemand.docstatus == 1) & (LoanDemand.loan_disbursement.isin(disbursement_names)))
		.groupby(LoanDemand.loan, LoanDemand.loan_disbursement, LoanDemand.demand_subtype)
	).run(as_dict=True)

	principal_overdue_map = {}
	interest_overdue_map = {}

	for row in raw_demand_data:
		key = (row["loan"], row["loan_disbursement"])
		if row["demand_subtype"] == "Principal":
			principal_overdue_map[key] = flt(row["outstanding"])
		elif row["demand_subtype"] == "Interest":
			interest_overdue_map[key] = flt(row["outstanding"])

	return principal_overdue_map, interest_overdue_map
