# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import flt

from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_current_pledges,
	get_current_pledges_by_loan,
)
from lending.loan_management.doctype.loan_security_shortfall.test_margin_call import (
	make_secured_loan,
	set_price,
)
from lending.loan_management.report.pledged_collateral.pledged_collateral import execute
from lending.tests.test_utils import (
	create_loan_security,
	create_loan_security_type,
	init_customers,
	init_loan_products,
	master_init,
)
from lending.tests.utils import LendingTestSuite


class TestPledgedCollateral(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		create_loan_security_type()
		create_loan_security()
		set_price(250)

	def test_shows_quantity_left_after_a_sale(self):
		applicant = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		loan = make_secured_loan(applicant)

		sale = frappe.new_doc("Loan Security Sale")
		sale.loan = loan
		sale.reason = "Borrower Request"
		sale.append("items", {"loan_security": "Test Security 2", "sold_qty": 3000, "sale_price": 250})
		sale.insert()
		sale.submit()

		_columns, data = execute({"company": "_Test Company", "loan": loan})
		self.assertEqual(len(data), 1)
		self.assertEqual(flt(data[0]["qty"]), 5000)
		self.assertEqual(flt(data[0]["value"]), 1250000)
		self.assertEqual(flt(data[0]["allowed_amount"]), 625000)

	def test_counting_many_loans_at_once_matches_counting_each(self):
		from lending.loan_management.doctype.loan.loan import unpledge_security

		first = make_secured_loan(frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name"))
		second = make_secured_loan(frappe.db.get_value("Customer", {"name": "_Test Loan Customer 1"}, "name"))

		# A sale on one loan and a release on the other
		sale = frappe.new_doc("Loan Security Sale")
		sale.loan = first
		sale.reason = "Borrower Request"
		sale.append("items", {"loan_security": "Test Security 2", "sold_qty": 3000, "sale_price": 250})
		sale.insert()
		sale.submit()
		set_price(500)
		unpledge_security(loan=second, security_map={"Test Security 2": 1000}, save=1, submit=1, approve=1)

		by_loan = get_current_pledges_by_loan([first, second])
		self.assertEqual(by_loan[first], get_current_pledges(loan=first))
		self.assertEqual(by_loan[second], get_current_pledges(loan=second))
		self.assertEqual(flt(by_loan[first]["Test Security 2"]), 5000)
		self.assertEqual(flt(by_loan[second]["Test Security 2"]), 7000)
