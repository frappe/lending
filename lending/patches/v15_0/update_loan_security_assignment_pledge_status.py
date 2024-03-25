# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	lsa = frappe.qb.DocType("Loan Security Assignment")

	(
		frappe.qb.update(lsa).set(
			lsa.status,
			(frappe.qb.terms.Case().when(lsa.status == "Requested", "Pledge Requested").else_(lsa.status)),
		)
	).run()
