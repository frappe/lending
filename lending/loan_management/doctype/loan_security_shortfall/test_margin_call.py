# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

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
	create_loan,
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
		frappe.db.set_value("Customer", self.applicant, "email_id", "borrower@example.com")

	def test_customer_who_never_pledged_gets_no_shortfall_and_an_old_one_closes(self):
		applicant = "_Test Loan Customer 1"
		frappe.db.delete("Sanctioned Loan Amount", {"applicant": applicant})
		frappe.db.set_value("Customer", applicant, "email_id", "unsecured@example.com")
		stale = frappe.get_doc(
			{
				"doctype": "Loan Security Shortfall",
				"applicant_type": "Customer",
				"applicant": applicant,
				"status": "Pending",
				"shortfall_amount": 280000,
			}
		)
		stale.flags.ignore_mandatory = True
		stale.insert(ignore_permissions=True)

		loan = create_loan(applicant, "Personal Loan", 280000, "Repay Over Number of Periods", 20, "Customer")
		loan.submit()
		make_loan_disbursement_entry(loan.name, 280000)
		# The check only runs on a site with secured lending
		make_secured_loan(self.applicant)
		# Another customer who pledged without a loan, so the applicant-wise loop runs too
		if not frappe.db.exists("Sanctioned Loan Amount", {"applicant": self.applicant}):
			frappe.get_doc(
				{
					"doctype": "Sanctioned Loan Amount",
					"applicant_type": "Customer",
					"applicant": self.applicant,
					"company": "_Test Company",
					"sanctioned_amount_limit": 1,
				}
			).insert(ignore_permissions=True)

		create_process_loan_security_shortfall()

		stale.reload()
		self.assertEqual(stale.status, "Completed")
		self.assertFalse(stale.cure_method)
		self.assertFalse(stale.notified_on)
		self.assertFalse(
			frappe.db.exists("Loan Security Shortfall", {"applicant": applicant, "status": ("!=", "Completed")})
		)

	def test_loan_with_its_own_pledge_gets_only_a_loan_shortfall(self):
		frappe.db.delete("Sanctioned Loan Amount", {"applicant": self.applicant})
		loan = make_secured_loan(self.applicant)

		set_price(200)
		create_process_loan_security_shortfall()

		self.assertEqual(frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "status"), "Notified")
		self.assertFalse(
			frappe.db.exists("Loan Security Shortfall", {"applicant": self.applicant, "loan": ("is", "not set")})
		)

	def test_applicant_shortfall_sends_no_second_notice(self):
		loan = make_secured_loan(self.applicant)
		# A top-up or a pledge without a loan gives the customer a Sanctioned Loan Amount
		if not frappe.db.exists("Sanctioned Loan Amount", {"applicant": self.applicant}):
			frappe.get_doc(
				{
					"doctype": "Sanctioned Loan Amount",
					"applicant_type": "Customer",
					"applicant": self.applicant,
					"company": "_Test Company",
					# The shortfall check sets the limit from the pledges
					"sanctioned_amount_limit": 1,
				}
			).insert(ignore_permissions=True)

		# At ₹200 the loan and the applicant are both short by the same ₹2,00,000
		set_price(200)
		create_process_loan_security_shortfall()

		self.assertEqual(frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "status"), "Notified")
		applicant_shortfall = frappe.db.get_value(
			"Loan Security Shortfall",
			{"applicant": self.applicant, "loan": ("is", "not set")},
			["status", "notified_on"],
			as_dict=1,
		)
		self.assertEqual(applicant_shortfall.status, "Pending")
		self.assertFalse(applicant_shortfall.notified_on)

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

	def test_draft_covers_what_the_proceeds_pay_before_principal(self):
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()

		sale = frappe.new_doc("Loan Security Sale")
		sale.loan = loan
		sale.reason = "Margin Call Not Cured"
		sale.loan_security_shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")
		sale.charges = 2000
		sale.deductions = 1000
		dues = {"interest_amount": 15000, "penalty_amount": 5000, "total_charges_payable": 0}
		with patch(
			"lending.loan_management.doctype.loan_security_sale.loan_security_sale.calculate_amounts",
			return_value=dues,
		):
			sale.prefill_items()

		self.assertEqual(flt(sale.shortfall_amount), 200000)
		self.assertEqual(flt(sale.overdue_dues), 20000)
		self.assertEqual(flt(sale.amount_to_recover), 223000)
		# Each unit at ₹200 with LTV 50 cures ₹100
		self.assertEqual(sale.items[0].qty, 2230)

	def test_follow_up_sale_is_drafted_once_the_proceeds_are_applied(self):
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")
		frappe.db.set_value("Loan Security Shortfall", shortfall, "cure_by", add_days(nowdate(), -1))
		process_open_shortfalls()

		# Staff sell only half of the 2,000 units drafted
		sale = frappe.get_doc("Loan Security Sale", {"loan_security_shortfall": shortfall})
		sale.items[0].sold_qty = 1000
		sale.items[0].sale_price = 200
		sale.submit()

		# Until the proceeds reach the loan, the shortfall looks larger than it is
		process_open_shortfalls()
		self.assertFalse(
			frappe.db.exists("Loan Security Sale", {"loan_security_shortfall": shortfall, "docstatus": 0})
		)

		sale.apply_proceeds()
		self.assertNotEqual(frappe.db.get_value("Loan Security Shortfall", shortfall, "status"), "Completed")
		process_open_shortfalls()
		follow_up = frappe.get_doc("Loan Security Sale", {"loan_security_shortfall": shortfall, "docstatus": 0})
		self.assertEqual(follow_up.items[0].qty, 1000)

	def test_escalated_shortfall_is_drafted_again_after_its_draft_is_deleted(self):
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")
		frappe.db.set_value("Loan Security Shortfall", shortfall, "cure_by", add_days(nowdate(), -1))
		process_open_shortfalls()
		self.assertEqual(frappe.db.get_value("Loan Security Shortfall", shortfall, "status"), "Escalated")

		frappe.delete_doc("Loan Security Sale", frappe.db.get_value("Loan Security Sale", {"loan_security_shortfall": shortfall}))
		process_open_shortfalls()
		self.assertTrue(
			frappe.db.exists("Loan Security Sale", {"loan_security_shortfall": shortfall, "docstatus": 0})
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

	def test_sell_level_of_a_security_no_longer_held_is_ignored(self):
		from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
			CollateralValuation,
		)

		frappe.db.set_value("Loan Security", "Test Security 1", "sell_ltv", 60)
		loan = make_secured_loan(self.applicant)

		# Security 1 sits in the map at 0, as a fully released or sold security does
		valuation = CollateralValuation()
		with patch(
			"lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall.get_pledged_security_qty",
			return_value={"Test Security 1": 0, "Test Security 2": 8000},
		):
			collateral = valuation.value_loan(loan)

		self.assertFalse(collateral.has_sell_level)

	def test_missing_price_holds_the_margin_call(self):
		frappe.db.set_value("Loan Security", "Test Security 2", "sell_ltv", 60)
		loan = make_secured_loan(self.applicant)

		frappe.db.delete("Loan Security Price", {"loan_security": "Test Security 2"})
		create_process_loan_security_shortfall()

		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan})
		self.assertTrue(shortfall.missing_price)
		self.assertEqual(shortfall.status, "Pending")
		self.assertFalse(shortfall.notified_on)

		# Once a real price below the sell level arrives, the margin call goes ahead
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall.reload()
		self.assertFalse(shortfall.missing_price)
		self.assertEqual(shortfall.status, "Sale Triggered")
		self.assertTrue(shortfall.notified_on)

	def test_borrower_without_email_is_flagged_and_not_notified(self):
		frappe.db.set_value("Customer", self.applicant, "email_id", None)
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()

		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan})
		self.assertTrue(shortfall.email_missing)
		self.assertEqual(shortfall.status, "Pending")
		self.assertFalse(shortfall.notified_on)
		self.assertFalse(shortfall.cure_by)

		# Once staff add the email, the next run sends the notice and starts the cure period
		frappe.db.set_value("Customer", self.applicant, "email_id", "borrower@example.com")
		process_open_shortfalls()
		shortfall.reload()
		self.assertFalse(shortfall.email_missing)
		self.assertEqual(shortfall.status, "Notified")
		self.assertTrue(shortfall.cure_by)

	def test_sale_above_sell_ltv_is_drafted_without_an_email(self):
		frappe.db.set_value("Customer", self.applicant, "email_id", None)
		frappe.db.set_value("Loan Security", "Test Security 2", "sell_ltv", 60)
		loan = make_secured_loan(self.applicant)

		# 62.5% is above the sell level of 60%
		set_price(200)
		create_process_loan_security_shortfall()

		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan})
		self.assertEqual(shortfall.status, "Sale Triggered")
		self.assertTrue(shortfall.email_missing)
		self.assertFalse(shortfall.notified_on)
		sale = frappe.get_doc("Loan Security Sale", {"loan_security_shortfall": shortfall.name})
		self.assertEqual(sale.docstatus, 0)

	def test_reminder_waits_for_prices_and_goes_once(self):
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")
		frappe.db.set_value("Loan Security Shortfall", shortfall, "cure_by", add_days(nowdate(), 2))

		# Prices gone: the check flags the shortfall, and no reminder goes out
		frappe.db.delete("Loan Security Price", {"loan_security": "Test Security 2"})
		create_process_loan_security_shortfall()
		self.assertFalse(frappe.db.get_value("Loan Security Shortfall", shortfall, "reminded_on"))

		set_price(200)
		create_process_loan_security_shortfall()
		reminded_on = frappe.db.get_value("Loan Security Shortfall", shortfall, "reminded_on")
		self.assertTrue(reminded_on)

		process_open_shortfalls()
		self.assertEqual(frappe.db.get_value("Loan Security Shortfall", shortfall, "reminded_on"), reminded_on)

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

	def test_pledge_too_small_at_ltv_keeps_the_shortfall_open(self):
		loan = make_secured_loan(self.applicant)
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": loan}, "name")

		# ₹3,00,000 more collateral covers only ₹1,50,000 at LTV 50, short of the ₹2,00,000 gap
		create_loan_security_assignment(
			loan=loan, securities=[{"loan_security": "Test Security 2", "qty": 1500, "haircut": 50}]
		)

		status, shortfall_amount = frappe.db.get_value(
			"Loan Security Shortfall", shortfall, ["status", "shortfall_amount"]
		)
		self.assertNotEqual(status, "Completed")
		self.assertEqual(flt(shortfall_amount, 2), 50000)

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
