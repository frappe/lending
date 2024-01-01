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

		doc.save()
