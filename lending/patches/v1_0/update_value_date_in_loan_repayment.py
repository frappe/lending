import frappe


def execute():
	# Update the value_date field in Loan Repayment
	frappe.db.sql(
		"""
        UPDATE `tabLoan Repayment`
        SET value_date = posting_date
        WHERE docstatus = 1
        AND value_date IS NULL
    """
	)
