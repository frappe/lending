import frappe


def execute():
	"""Set the Loan Disbursement on repayment schedules made in version 15.

	In version 15 the schedule was made from the Loan, so these schedules have no Loan Disbursement.
	"""
	LRS = frappe.qb.DocType("Loan Repayment Schedule")

	loans = (
		frappe.qb.from_(LRS)
		.select(LRS.loan)
		.distinct()
		.where(
			(LRS.docstatus == 1)
			& ((LRS.loan_disbursement.isnull()) | (LRS.loan_disbursement == ""))
			& ((LRS.repayment_schedule_type.isnull()) | (LRS.repayment_schedule_type != "Line of Credit"))
		)
		.run(pluck=True)
	)

	for loan in loans:
		# A version 15 loan can have many disbursements but only one schedule, so use the latest
		disbursement = frappe.db.get_value(
			"Loan Disbursement",
			{"against_loan": loan, "docstatus": 1},
			"name",
			order_by="disbursement_date desc, creation desc",
		)
		if not disbursement:
			continue

		# Restructured loans keep their older submitted schedules, so link all of them
		for schedule in frappe.get_all(
			"Loan Repayment Schedule",
			filters={"loan": loan, "docstatus": 1, "loan_disbursement": ["in", ["", None]]},
			pluck="name",
		):
			frappe.db.set_value(
				"Loan Repayment Schedule", schedule, "loan_disbursement", disbursement, update_modified=False
			)
