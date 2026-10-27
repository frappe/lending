# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import flt

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
