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

	def test_reader_restricted_to_another_company_sees_no_rows(self):
		from lending.loan_management.report.ltv_by_loan.ltv_by_loan import execute as ltv_by_loan

		applicant = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		loan = make_secured_loan(applicant)
		set_price(200)
		create_process_loan_security_shortfall()

		def loans_seen_by(user):
			frappe.set_user(user)
			try:
				_columns, ageing = execute({"company": "_Test Company"})
				_columns, ltv = ltv_by_loan({"company": "_Test Company"})
			finally:
				frappe.set_user("Administrator")
			return {row["loan"] for row in ageing}, {row["loan"] for row in ltv}

		ageing, ltv = loans_seen_by(make_reporter_restricted_to("_Test Company 1"))
		self.assertNotIn(loan, ageing)
		self.assertNotIn(loan, ltv)

		ageing, ltv = loans_seen_by(make_reporter_restricted_to("_Test Company"))
		self.assertIn(loan, ageing)
		self.assertIn(loan, ltv)

	def test_buckets(self):
		self.assertEqual(get_bucket(0), "0-7")
		self.assertEqual(get_bucket(7), "0-7")
		self.assertEqual(get_bucket(30), "16-30")
		self.assertEqual(get_bucket(31), "31+")


def make_reporter_restricted_to(company):
	email = f"_test_reporter_{frappe.scrub(company)}@example.com"
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Loan Reporter", "send_welcome_email": 0}
		).insert()
	frappe.get_doc("User", email).add_roles("Loan Reporter")
	frappe.get_doc(
		{"doctype": "User Permission", "user": email, "allow": "Company", "for_value": company}
	).insert()
	return email
