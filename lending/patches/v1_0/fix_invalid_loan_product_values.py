import frappe


def execute():
	fields_to_fix = {
		"cyclic_day_of_the_month": 0,
		"grace_period_in_days": 0,
		"rate_of_interest": 0.0,
		"maximum_loan_amount": 0.0,
		"is_term_loan": 0,
		"penalty_interest_rate": 0.0,
		"days_past_due_threshold_for_npa": 0,
		"excess_amount_acceptance_limit": 0.0,
		"disabled": 0,
		"validate_normal_repayment": 0,
		"same_as_regular_interest_accounts": 0,
		"min_days_bw_disbursement_first_repayment": 0,
		"write_off_amount": 0.0,
	}

	if not frappe.db.table_exists("Loan Product"):
		return

	for field, default in fields_to_fix.items():
		if field not in frappe.db.get_table_columns("Loan Product"):
			continue

		# Use backticks to ensure field names with special characters are handled correctly
		field_sql = f"`{field}`"

		condition = (
			"CAST({field} AS CHAR) IS NULL "
			"OR CAST({field} AS CHAR) = '' "
			"OR CAST({field} AS CHAR) NOT REGEXP '^-?[0-9]+(\\.[0-9]+)?$'"
		).format(field=field_sql)

		query = "UPDATE `tabLoan Product` SET {field} = %s WHERE {condition}".format(
			field=field_sql, condition=condition
		)

		frappe.db.sql(query, (default,))
