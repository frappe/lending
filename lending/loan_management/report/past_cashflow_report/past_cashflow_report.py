import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 200},
		{"label": _("Applicant Name"), "fieldname": "applicant", "fieldtype": "Data", "width": 150},
		{
			"label": _("Loan Product"),
			"fieldname": "loan_product",
			"fieldtype": "Link",
			"options": "Loan Product",
			"width": 150,
		},
		{
			"label": _("Principal Amount"),
			"fieldname": "principal_amount",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Interest Amount"),
			"fieldname": "interest_amount",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Additional Interest"),
			"fieldname": "additional_interest",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Total Charges Paid"),
			"fieldname": "total_charges_paid",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Total Penalty Paid"),
			"fieldname": "total_penalty_paid",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Excess Amount"),
			"fieldname": "excess_amount",
			"fieldtype": "Currency",
			"width": 150,
		},
		{"label": _("Year-Month"), "fieldname": "year_month", "fieldtype": "Data", "width": 120},
	]


def get_data(filters):
	data = []

	if not filters.get("as_of_date"):
		frappe.throw(_("Please select a date."))

	params = {"as_of_date": filters["as_of_date"]}

	where_conditions = [
		"tlr.docstatus = 1",
		"tlr.posting_date <= %(as_of_date)s",
		"tlr.repayment_type NOT IN ('Principal Adjustment', 'Interest Waiver', 'Penalty Waiver', 'Charges Waiver')",
	]

	for fl in ("company", "loan_product", "applicant", "loan"):
		if filters.get(fl):
			if fl == "loan":
				where_conditions.append("tlr.against_loan = %({})s".format(fl))
			else:
				where_conditions.append("tlr.{0} = %({0})s".format(fl))
			params[fl] = filters[fl]

	where_clause = " AND ".join(where_conditions)

	query = """
		SELECT
			tlr.against_loan AS loan,
			tlr.applicant AS applicant,
			tlr.loan_product AS loan_product,
			SUM(tlr.principal_amount_paid) AS principal_amount,
			SUM(tlr.total_interest_paid) AS interest_amount,
			SUM(tlr.unbooked_interest_paid) AS additional_interest,
			SUM(tlr.total_charges_paid) AS total_charges_paid,
			SUM(tlr.total_penalty_paid) AS total_penalty_paid,
			SUM(tlr.excess_amount) AS excess_amount,
			CONCAT(YEAR(tlr.posting_date), '-', LPAD(MONTH(tlr.posting_date), 2, '0')) AS yyyy_mm
		FROM
			`tabLoan Repayment` tlr
		WHERE
			{where_clause}
		GROUP BY
			tlr.against_loan, yyyy_mm
		ORDER BY
			tlr.against_loan, yyyy_mm
	""".format(
		where_clause=where_clause
	)

	records = frappe.db.sql(query, params, as_dict=True)

	for row in records:
		data.append(
			{
				"loan": row.loan,
				"applicant": row.applicant,
				"loan_product": row.loan_product,
				"principal_amount": round(row.principal_amount or 0, 2),
				"interest_amount": round(row.interest_amount or 0, 2),
				"additional_interest": round(row.additional_interest or 0, 2),
				"total_charges_paid": round(row.total_charges_paid or 0, 2),
				"total_penalty_paid": round(row.total_penalty_paid or 0, 2),
				"excess_amount": round(row.excess_amount or 0, 2),
				"year_month": row.yyyy_mm,
			}
		)

	return data
