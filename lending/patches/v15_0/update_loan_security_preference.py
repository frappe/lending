# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	loan = frappe.qb.DocType("Loan")

	(
		frappe.qb.update(loan).set(
			loan.loan_security_preference,
			(
				frappe.qb.terms.Case()
				.when(loan.is_secured_loan == 0, "Unsecured")
				.when(loan.is_secured_loan == 1, "Secured")
			),
		)
	).run()

	la = frappe.qb.DocType("Loan Application")

	(
		frappe.qb.update(la).set(
			la.loan_security_preference,
			(
				frappe.qb.terms.Case()
				.when(la.is_secured_loan == 0, "Unsecured")
				.when(la.is_secured_loan == 1, "Secured")
			),
		)
	).run()
