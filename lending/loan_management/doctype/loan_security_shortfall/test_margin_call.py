# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall import (
	create_process_loan_security_shortfall,
)
from lending.loan_management.margin_call import process_open_shortfalls
from lending.loan_management.utils import add_working_days
from lending.tests.test_utils import (
	create_loan_application,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_with_security,
	create_repayment_entry,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)
from lending.tests.utils import LendingTestSuite


class TestMarginCall(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		create_loan_security_type()
		create_loan_security()
		frappe.db.set_value("Loan Security Type", "Stock", "sell_ltv", 0)
		frappe.db.set_value("Loan Security", "Test Security 2", "sell_ltv", 0)
		frappe.db.set_single_value("Lending Settings", {"enable_margin_call": 1, "margin_cure_days": 7})
		set_price(250)
		self.applicant = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_shortfall_is_notified_then_escalated_to_a_draft_sale(self):
		# 8,000 units at ₹250 with haircut 50 lend ₹10,00,000
		loan = make_secured_loan(self.applicant)

		# At ₹200 the loan is 62.5% of ₹16,00,000, above LTV 50
		set_price(200)
		create_process_loan_security_shortfall()

		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan})
		self.assertEqual(shortfall.status, "Notified")
		self.assertEqual(flt(shortfall.shortfall_percentage, 2), 62.5)
		self.assertTrue(shortfall.notified_on)
		holiday_list = frappe.get_cached_value("Company", "_Test Company", "default_holiday_list")
		self.assertEqual(getdate(shortfall.cure_by), add_working_days(nowdate(), 7, holiday_list))

		# A later run keeps the notice date and the deadline
		create_process_loan_security_shortfall()
		shortfall_after = frappe.get_doc("Loan Security Shortfall", shortfall.name)
		self.assertEqual(shortfall_after.notified_on, shortfall.notified_on)
		self.assertEqual(shortfall_after.status, "Notified")

		frappe.db.set_value("Loan Security Shortfall", shortfall.name, "cure_by", add_days(nowdate(), -1))
		process_open_shortfalls()
		self.assertEqual(frappe.db.get_value("Loan Security Shortfall", shortfall.name, "status"), "Escalated")

		sale = frappe.get_doc("Loan Security Sale", {"loan_security_shortfall": shortfall.name})
		self.assertEqual(sale.docstatus, 0)
		self.assertEqual(sale.reason, "Margin Call Not Cured")
		self.assertEqual(sale.items[0].qty, 2000)

		# Staff selling the collateral moves the shortfall to Sale Triggered
		sale.items[0].sold_qty = 2000
		sale.items[0].sale_price = 200
		sale.submit()
		self.assertEqual(
			frappe.db.get_value("Loan Security Shortfall", shortfall.name, "status"), "Sale Triggered"
		)

	def test_cure_discards_the_untouched_draft_and_blocks_a_filled_one(self):
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")

		frappe.db.set_value("Loan Security Shortfall", shortfall, "cure_by", add_days(nowdate(), -1))
		process_open_shortfalls()
		drafted = frappe.db.get_value("Loan Security Sale", {"loan_security_shortfall": shortfall}, "name")

		# Staff start a second sale by hand and fill in what they sold
		filled = frappe.new_doc("Loan Security Sale")
		filled.loan = loan
		filled.reason = "Margin Call Not Cured"
		filled.loan_security_shortfall = shortfall
		filled.append("items", {"loan_security": "Test Security 2", "sold_qty": 100, "sale_price": 250})
		filled.insert()

		set_price(250)
		create_process_loan_security_shortfall()
		self.assertEqual(frappe.db.get_value("Loan Security Shortfall", shortfall, "status"), "Completed")
		self.assertFalse(frappe.db.exists("Loan Security Sale", drafted))

		with self.assertRaises(frappe.ValidationError):
			filled.submit()

	def test_above_sell_ltv_triggers_a_sale_at_once(self):
		frappe.db.set_value("Loan Security", "Test Security 2", "sell_ltv", 60)
		loan = make_secured_loan(self.applicant)

		# 62.5% is above the sell level of 60%
		set_price(200)
		create_process_loan_security_shortfall()

		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan})
		self.assertEqual(shortfall.status, "Sale Triggered")
		self.assertTrue(shortfall.notified_on)
		self.assertTrue(frappe.db.exists("Loan Security Sale", {"loan_security_shortfall": shortfall.name}))

	def test_cure_by_repayment(self):
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")

		repayment = create_repayment_entry(loan, nowdate(), 300000)
		repayment.submit()
		create_process_loan_security_shortfall()

		status, cure_method = frappe.db.get_value(
			"Loan Security Shortfall", shortfall, ["status", "cure_method"]
		)
		self.assertEqual(status, "Completed")
		self.assertEqual(cure_method, "Repayment")

	def test_cure_by_additional_pledge(self):
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")

		create_loan_security_assignment(
			loan=loan, securities=[{"loan_security": "Test Security 2", "qty": 4000, "haircut": 50}]
		)

		status, cure_method = frappe.db.get_value(
			"Loan Security Shortfall", shortfall, ["status", "cure_method"]
		)
		self.assertEqual(status, "Completed")
		self.assertEqual(cure_method, "Additional Pledge")

	def test_drawdown_blocked_while_short(self):
		loan = make_secured_loan(self.applicant, disbursed_amount=700000)
		set_price(100)
		create_process_loan_security_shortfall()

		with self.assertRaises(frappe.ValidationError):
			make_loan_disbursement_entry(loan, 10000)

	def test_nothing_happens_with_margin_call_off(self):
		frappe.db.set_single_value("Lending Settings", "enable_margin_call", 0)
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()

		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan})
		self.assertEqual(shortfall.status, "Pending")
		self.assertFalse(shortfall.notified_on)

	def test_sell_ltv_cannot_be_below_ltv(self):
		security_type = frappe.get_doc("Loan Security Type", "Stock")
		security_type.sell_ltv = 40
		with self.assertRaises(frappe.ValidationError):
			security_type.save()


def set_price(price):
	create_loan_security_price(
		"Test Security 2", price, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
	)


def make_secured_loan(applicant, disbursed_amount=None):
	pledges = [{"loan_security": "Test Security 2", "qty": 8000, "haircut": 50}]
	loan_application = create_loan_application(
		"_Test Company", applicant, "Stock Loan", pledges, "Repay Over Number of Periods", 12
	)
	create_loan_security_assignment(loan_application)
	loan = create_loan_with_security(
		applicant, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
	)
	loan.submit()
	make_loan_disbursement_entry(loan.name, disbursed_amount or loan.loan_amount)
	return loan.name
