# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, nowdate

from lending.loan_management.doctype.loan_security_shortfall.test_margin_call import (
	make_secured_loan,
	set_price,
)
from lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall import (
	create_process_loan_security_shortfall,
)
from lending.loan_management.report.shortfall_ageing.shortfall_ageing import execute, get_bucket
from lending.tests.test_utils import (
	create_loan_security,
	create_loan_security_type,
	init_customers,
	init_loan_products,
	master_init,
)
from lending.tests.utils import LendingTestSuite


class TestShortfallAgeing(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		create_loan_security_type()
		create_loan_security()
		frappe.db.set_single_value("Lending Settings", "enable_margin_call", 0)
		set_price(250)

	def test_open_shortfall_with_its_age(self):
		applicant = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		loan = make_secured_loan(applicant)
		set_price(200)
		create_process_loan_security_shortfall()

		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")
		frappe.db.set_value("Loan Security Shortfall", shortfall, "creation", add_days(nowdate(), -10))
		frappe.db.set_value("Loan Security Shortfall", shortfall, "cure_by", add_days(nowdate(), -2))

		_columns, data = execute({"company": "_Test Company"})
		row = next(row for row in data if row["loan_security_shortfall"] == shortfall)
		self.assertEqual(row["days_open"], 10)
		self.assertEqual(row["ageing"], "8-15")
		self.assertEqual(row["days_past_cure_by"], 2)

		_columns, data = execute({"company": "_Test Company", "status": "Escalated"})
		self.assertNotIn(shortfall, [row["loan_security_shortfall"] for row in data])

	def test_buckets(self):
		self.assertEqual(get_bucket(0), "0-7")
		self.assertEqual(get_bucket(7), "0-7")
		self.assertEqual(get_bucket(30), "16-30")
		self.assertEqual(get_bucket(31), "31+")
