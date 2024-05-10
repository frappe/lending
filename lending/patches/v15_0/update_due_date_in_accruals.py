import frappe


def execute():
	frappe.db.sql(
		"""
		UPDATE `tabLoan Interest Accrual`
		SET due_date = posting_date
		WHERE ifnull(due_date, '') = ''
	"""
	)
