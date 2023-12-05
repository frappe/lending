# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	lsa = frappe.qb.DocType("Loan Security Assignment")

	new_status = (
		frappe.qb.terms.Case()
		.when(lsa.status == "Pledge Requested", "Assignment Requested")
		.when(lsa.status == "Unpledged", "Unassigned")
		.when(lsa.status == "Pledged", "Assigned")
		.else_(lsa.status)
	)

	(frappe.qb.update(lsa).set(lsa.status, new_status)).run()
