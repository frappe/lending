# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	lca = frappe.qb.DocType("Loan Collateral Assignment")
	frappe.qb.update(lca).set(lca.collateral_type, "Loan Security").where(
		lca.collateral_type.isnull()
	).run()

	lcd = frappe.qb.DocType("Loan Collateral Deassignment")
	frappe.qb.update(lcd).set(lcd.collateral_type, "Loan Security").where(
		lcd.collateral_type.isnull()
	).run()

	la = frappe.qb.DocType("Loan Application")
	frappe.qb.update(la).set(la.collateral_type, "Loan Security").where(
		la.is_secured_loan == 1
	).where(la.collateral_type.isnull()).run()

	l = frappe.qb.DocType("Loan")
	frappe.qb.update(l).set(l.collateral_type, "Loan Security").where(l.is_secured_loan == 1).where(
		l.collateral_type.isnull()
	).run()
