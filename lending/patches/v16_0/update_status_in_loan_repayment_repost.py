import frappe


def execute():
	if not frappe.db.has_column("Loan Repayment Repost", "status"):
		return

	repost = frappe.qb.DocType("Loan Repayment Repost")

	frappe.qb.update(repost).set(repost.status, "Completed").where(repost.docstatus == 1).run()

	frappe.qb.update(repost).set(repost.status, "Cancelled").where(repost.docstatus == 2).run()

	(
		frappe.qb.update(repost)
		.set(repost.status, "Draft")
		.where((repost.docstatus == 0) & (repost.status.isnull() | (repost.status == "")))
		.run()
	)
