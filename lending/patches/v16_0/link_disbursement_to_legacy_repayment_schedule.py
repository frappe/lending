import frappe
from frappe.query_builder import Case

# Older plans of a restructured loan are history, so they are not linked
HISTORY_STATUSES = ("Rescheduled", "Restructured", "Cancelled")


def execute():
	"""Set the Loan Disbursement on repayment schedules made in version 15.

	In version 15 the schedule was made from the Loan, so these schedules have no Loan Disbursement.
	"""
	LRS = frappe.qb.DocType("Loan Repayment Schedule")

	loans = (
		frappe.qb.from_(LRS)
		.select(LRS.loan)
		.distinct()
		.where(is_unlinked(LRS))
		.where((LRS.repayment_schedule_type.isnull()) | (LRS.repayment_schedule_type != "Line of Credit"))
		.run(pluck=True)
	)

	for loan in loans:
		disbursement = get_latest_free_disbursement(loan)
		schedule = get_current_schedule(loan)

		if disbursement and schedule:
			frappe.qb.update(LRS).set(LRS.loan_disbursement, disbursement).where(
				LRS.name == schedule
			).run()


def is_unlinked(LRS):
	return (LRS.docstatus == 1) & ((LRS.loan_disbursement.isnull()) | (LRS.loan_disbursement == ""))


def get_latest_free_disbursement(loan):
	"""A version 15 loan can have many disbursements but only one schedule, so use the latest.

	Disbursements which already have a schedule are skipped, as they were made after the update.
	"""
	LD = frappe.qb.DocType("Loan Disbursement")
	LRS = frappe.qb.DocType("Loan Repayment Schedule")

	used = (
		frappe.qb.from_(LRS)
		.select(LRS.loan_disbursement)
		.where((LRS.loan == loan) & (LRS.docstatus == 1) & (LRS.loan_disbursement.isnotnull()))
		.where(LRS.loan_disbursement != "")
	)

	names = (
		frappe.qb.from_(LD)
		.select(LD.name)
		.where((LD.against_loan == loan) & (LD.docstatus == 1))
		.where(LD.name.notin(used))
		.orderby(LD.disbursement_date, order=frappe.qb.desc)
		.orderby(LD.creation, order=frappe.qb.desc)
		.limit(1)
		.run(pluck=True)
	)
	return names[0] if names else None


def get_current_schedule(loan):
	"""Restructured loans keep older schedules, so link only the one in use"""
	LRS = frappe.qb.DocType("Loan Repayment Schedule")

	names = (
		frappe.qb.from_(LRS)
		.select(LRS.name)
		.where(LRS.loan == loan)
		.where(is_unlinked(LRS))
		.where(LRS.status.notin(HISTORY_STATUSES))
		.orderby(Case().when(LRS.status == "Active", 0).else_(1))
		.orderby(LRS.creation, order=frappe.qb.desc)
		.limit(1)
		.run(pluck=True)
	)
	return names[0] if names else None
