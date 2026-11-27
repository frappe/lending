import frappe
from frappe.utils import create_batch


def execute():
	# Only term loans that are not Line of Credit show this field, so only they can be missing it by mistake.
	Loan = frappe.qb.DocType("Loan")
	loans = (
		frappe.qb.from_(Loan)
		.select(Loan.name)
		.where(
			(Loan.is_term_loan == 1)
			& (Loan.repayment_schedule_type.isnull() | (Loan.repayment_schedule_type != "Line of Credit"))
			& (Loan.repayment_frequency.isnull() | (Loan.repayment_frequency == ""))
		)
	).run(pluck=True)

	for batch in create_batch(loans, 1000):
		for doctype, loan_field, field in (
			("Loan", "name", "repayment_frequency"),
			("Loan Repayment Schedule", "loan", "repayment_frequency"),
			("Loan Restructure", "loan", "old_repayment_frequency"),
		):
			table = frappe.qb.DocType(doctype)
			(
				frappe.qb.update(table)
				.set(table[field], "Monthly")
				.where(table[loan_field].isin(batch))
				.where(table[field].isnull() | (table[field] == ""))
			).run()
