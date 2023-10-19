# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe


def execute():
	lca = frappe.qb.DocType("Loan Collateral Assignment")

	(
		frappe.qb.update(lca).set(
			lca.status,
			(
				frappe.qb.terms.Case()
				.when(lca.status == "Unpledged", "Unassigned")
				.when(lca.status == "Pledged", "Assigned")
				.else_(lca.status)
			),
		)
	).run()
