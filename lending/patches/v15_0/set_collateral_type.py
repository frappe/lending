# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	lsp = frappe.qb.DocType("Loan Security Pledge")
	frappe.qb.update(lsp).set(lsp.collateral_type, "Loan Security").where(
		lsp.collateral_type.isnull()
	).run()

	la = frappe.qb.DocType("Loan Application")
	frappe.qb.update(la).set(la.collateral_type, "Loan Security").where(
		la.is_secured_loan == 1
	).where(la.collateral_type.isnull()).run()

	l = frappe.qb.DocType("Loan")
	frappe.qb.update(l).set(l.collateral_type, "Loan Security").where(l.is_secured_loan == 1).where(
		l.collateral_type.isnull()
	).run()
