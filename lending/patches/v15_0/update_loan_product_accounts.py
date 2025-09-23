import frappe


def execute():
	for product in frappe.db.get_all("Loan Product"):
		doc = frappe.get_doc("Loan Product", product.name)
		if not doc.interest_receivable_account:
			doc.interest_receivable_account = doc.interest_income_account

		if not doc.interest_accrued_account:
			doc.interest_accrued_account = doc.interest_income_account

		if not doc.penalty_receivable_account:
			doc.penalty_receivable_account = doc.penalty_income_account

		if not doc.penalty_accrued_account:
			doc.penalty_accrued_account = doc.penalty_income_account

		if not doc.customer_refund_account:
			doc.customer_refund_account = doc.loan_account

		if not doc.security_deposit_account:
			doc.security_deposit_account = doc.loan_account

		if not doc.write_off_recovery_account:
			doc.write_off_recovery_account = doc.interest_income_account

		if not doc.interest_waiver_account:
			doc.interest_waiver_account = doc.interest_income_account

		if not doc.penalty_waiver_account:
			doc.penalty_waiver_account = doc.penalty_income_account

		if not doc.broken_period_interest_recovery_account:
			doc.broken_period_interest_recovery_account = doc.interest_income_account

		doc.save()
