import frappe
from frappe.query_builder import Field
from frappe.query_builder.functions import Cast_


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

	loan_product = frappe.qb.DocType("Loan Product")

	for field, default in fields_to_fix.items():
		if field not in frappe.db.get_table_columns("Loan Product"):
			continue

		field_col = Field(field)
		field_as_char = Cast_(field_col, "CHAR")

		# Set only if value is NULL, empty, or starts with non-numeric character
		(
			frappe.qb.update(loan_product)
			.set(field_col, default)
			.where(
				field_as_char.isnull()
				| (field_as_char == "")
				| (~field_as_char.regexp(r"^-?[0-9]+(\.[0-9]+)?$"))
			)
		).run()
