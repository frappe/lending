# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import flt

from lending.loan_management.doctype.loan_security_shortfall.test_margin_call import (
	make_secured_loan,
	set_price,
)
from lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall import (
	create_process_loan_security_shortfall,
)
from lending.loan_management.report.ltv_by_loan.ltv_by_loan import execute
from lending.tests.test_utils import (
	create_loan_security,
	create_loan_security_type,
	init_customers,
	init_loan_products,
	master_init,
)
from lending.tests.utils import LendingTestSuite


class TestLTVByLoan(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		create_loan_security_type()
		create_loan_security()
		frappe.db.set_value("Loan Security", "Test Security 2", "sell_ltv", 70)
		frappe.db.set_single_value("Lending Settings", "enable_margin_call", 0)
		set_price(250)

	def test_loan_above_ltv(self):
		applicant = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		loan = make_secured_loan(applicant)
		set_price(200)
		create_process_loan_security_shortfall()

		_columns, data = execute({"company": "_Test Company", "only_above_ltv": 1})
		row = next(row for row in data if row["loan"] == loan)

		# ₹10,00,000 against 8,000 units at ₹200
		self.assertEqual(flt(row["security_value"], 2), 1600000)
		self.assertEqual(flt(row["allowed_amount"], 2), 800000)
		self.assertEqual(flt(row["headroom"], 2), -200000)
		self.assertEqual(flt(row["current_ltv"], 2), 62.5)
		self.assertEqual(flt(row["ltv_limit"], 2), 50)
		self.assertEqual(flt(row["sell_ltv"], 2), 70)
		self.assertEqual(row["shortfall_status"], "Pending")

		set_price(250)
		_columns, data = execute({"company": "_Test Company", "only_above_ltv": 1})
		self.assertNotIn(loan, [row["loan"] for row in data])
