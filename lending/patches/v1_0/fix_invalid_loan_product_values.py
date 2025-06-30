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

		condition = f"""(`{field}` IS NULL OR `{field}` NOT REGEXP '^-?[0-9]+(\\.[0-9]+)?$')"""
		query = f"""UPDATE `tabLoan Product` SET `{field}` = %s WHERE {condition}"""
		frappe.db.sql(query, (default,))
