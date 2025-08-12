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
	]


def get_data(filters):
	data = []

	if not filters.get("as_on_date"):
		frappe.throw(_("Please select a date."))

	params = {"as_on_date": filters["as_on_date"]}

	where_conditions = [
		"tlr.docstatus = 1",
		"tlr.posting_date <= %(as_on_date)s",
		"tlr.repayment_type NOT IN ('Interest Waiver', 'Penalty Waiver', 'Charges Waiver')",
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
			SUM(tlr.excess_amount) AS excess_amount
		FROM
			`tabLoan Repayment` tlr
		WHERE
			{where_clause}
		GROUP BY
			tlr.against_loan
		ORDER BY
			tlr.against_loan
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
				"principal_amount": row.principal_amount or 0,
				"interest_amount": row.interest_amount or 0,
				"additional_interest": row.additional_interest or 0,
				"total_charges_paid": row.total_charges_paid or 0,
				"total_penalty_paid": row.total_penalty_paid or 0,
				"excess_amount": row.excess_amount or 0,
			}
		)

	return data
