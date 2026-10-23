# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, flt, nowdate

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)
from lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall import (
	create_process_loan_security_shortfall,
)
from lending.tests.test_utils import (
	create_loan,
	create_loan_application,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_with_security,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)
from lending.tests.utils import LendingTestSuite


class TestLoanSecuritySale(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		create_loan_security_type()
		create_loan_security()
		set_price(250)
		self.applicant = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

		# 8,000 units at ₹250 with haircut 50 lend ₹10,00,000
		self.loan = make_secured_loan(self.applicant, 8000)
		self.assignment = frappe.db.get_value("Loan Security Assignment", {"loan": self.loan}, "name")

	def test_partial_sale_cures_the_shortfall(self):
		# At ₹200, LTV 50 allows ₹8,00,000 against ₹10,00,000 drawn
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": self.loan, "status": "Pending"})
		self.assertEqual(flt(shortfall.shortfall_amount), 200000)

		sale = make_sale(self.loan, loan_security_shortfall=shortfall.name)
		sale.prefill_items()

		# Each unit sold cures ₹100: it repays ₹200 and takes ₹100 off the allowed amount
		self.assertEqual(len(sale.items), 1)
		self.assertEqual(sale.items[0].qty, 2000)

		sell(sale, {"Test Security 2": (2000, 200)})
		self.assertEqual(get_pledged_security_qty(loan=self.loan)["Test Security 2"], 6000)
		self.assertEqual(
			frappe.db.get_value("Loan Security Assignment", self.assignment, "status"), "Pledged"
		)

		sale.apply_proceeds()
		sale.reload()
		self.assertEqual(sale.status, "Proceeds Applied")
		self.assertEqual(len(sale.repayments), 1)
		self.assertEqual(
			frappe.db.get_value("Loan Repayment", sale.repayments[0].loan_repayment, "amount_paid"), 400000
		)
		self.assertEqual(flt(sale.surplus_amount), 0)

		create_process_loan_security_shortfall()
		self.assertEqual(frappe.db.get_value("Loan Security Shortfall", shortfall.name, "status"), "Completed")

	def test_proceeds_that_do_not_cover_the_lost_cover_leave_the_shortfall_open(self):
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": self.loan, "status": "Pending"})

		# Selling 1,000 units at ₹200 repays ₹2,00,000 but also takes ₹1,00,000 off the allowed amount
		sale = make_sale(self.loan, loan_security_shortfall=shortfall.name)
		sale.append("items", {"loan_security": "Test Security 2", "qty": 1000})
		sell(sale, {"Test Security 2": (1000, 200)})
		self.assertEqual(
			flt(frappe.db.get_value("Loan Security Shortfall", shortfall.name, "shortfall_amount")), 300000
		)

		sale.apply_proceeds()
		shortfall.reload()
		self.assertEqual(shortfall.status, "Sale Triggered")
		self.assertGreaterEqual(flt(shortfall.shortfall_amount), 100000)

	def test_sold_collateral_no_longer_supports_a_drawdown(self):
		from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
			get_disbursal_amount,
		)

		loan = make_secured_loan(self.applicant, 8000, disbursed_amount=500000)
		self.assertEqual(flt(get_disbursal_amount(loan)[0]), 500000)

		# The 4,000 units sold added ₹5,00,000 of the ₹10,00,000 limit when they were pledged
		sale = make_sale(loan, reason="Borrower Request")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 4000})
		sell(sale, {"Test Security 2": (4000, 250)})

		self.assertLessEqual(flt(get_disbursal_amount(loan)[0]), 0)
		with self.assertRaises(frappe.ValidationError):
			make_loan_disbursement_entry(loan, 100000)

	def test_ledger_shows_each_sale_on_its_own_row(self):
		from lending.loan_management.report.loan_security_ledger.loan_security_ledger import execute

		for qty in (1000, 2000):
			sale = make_sale(self.loan, reason="Loan Default")
			sale.append("items", {"loan_security": "Test Security 2", "qty": qty})
			sell(sale, {"Test Security 2": (qty, 250)})

		_columns, rows = execute(frappe._dict(loan=self.loan, loan_security="Test Security 2"))
		self.assertEqual([row.qty for row in rows], [8000, 1000, 2000])
		self.assertEqual([row.balance_qty for row in rows], [8000, 7000, 5000])

	def test_full_sale_records_surplus_and_repossesses(self):
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 8000})
		sell(sale, {"Test Security 2": (8000, 200)})

		self.assertEqual(get_pledged_security_qty(loan=self.loan)["Test Security 2"], 0)
		self.assertEqual(
			frappe.db.get_value("Loan Security Assignment", self.assignment, "status"), "Repossessed"
		)

		sale.apply_proceeds()
		sale.reload()
		amount_paid = sum(flt(row.amount) for row in sale.repayments)
		self.assertGreaterEqual(amount_paid, 1000000)
		self.assertEqual(flt(sale.surplus_amount, 2), flt(1600000 - amount_paid, 2))

	def test_deductions_are_kept_out_of_the_repayment(self):
		# 8,000 units redeemed at ₹200 with 1% exit load: the fund house pays ₹15,84,000
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 8000})
		sale.deductions = 16000
		sell(sale, {"Test Security 2": (8000, 200)})
		self.assertEqual(flt(sale.net_proceeds), 1584000)

		sale.apply_proceeds()
		sale.reload()
		amount_paid = sum(flt(row.amount) for row in sale.repayments)
		self.assertGreaterEqual(amount_paid, 1000000)
		self.assertEqual(flt(sale.surplus_amount, 2), flt(1584000 - amount_paid, 2))

	def test_deductions_and_charges_cannot_exceed_gross_proceeds(self):
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 1000})
		# A draft keeps deductions entered before the sale is done
		sale.deductions = 150000
		sale.charges = 60000
		sale.save()

		with self.assertRaisesRegex(frappe.ValidationError, "Deductions and Charges"):
			sell(sale, {"Test Security 2": (1000, 200)})

	def test_proceeds_above_dues_are_applied_when_the_product_caps_normal_repayment(self):
		frappe.db.set_value("Loan Product", "Stock Loan", "validate_normal_repayment", 1)

		sale = make_sale(self.loan, reason="Borrower Request")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 1000})
		sell(sale, {"Test Security 2": (1000, 250)})
		sale.apply_proceeds()
		sale.reload()

		self.assertEqual(sale.repayments[0].repayment_type, "Pre Payment")
		self.assertEqual(flt(sale.repayments[0].amount), 250000)

	def test_line_of_credit_proceeds_repay_each_disbursement(self):
		loan = make_line_of_credit_loan(self.applicant)
		sale = make_sale(loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 2000})
		sell(sale, {"Test Security 2": (2000, 250)})
		sale.apply_proceeds()
		sale.reload()

		self.assertEqual(len(sale.repayments), 2)
		self.assertTrue(all(row.loan_disbursement for row in sale.repayments))
		for row in sale.repayments:
			self.assertEqual(
				frappe.db.get_value("Loan Repayment", row.loan_repayment, "loan_disbursement"),
				row.loan_disbursement,
			)

	def test_line_of_credit_proceeds_pay_the_sale_charge(self):
		from lending.tests.test_utils import add_or_update_loan_charges

		add_or_update_loan_charges("Term Loan Product 5")
		frappe.db.set_single_value("Lending Settings", "sale_charge", "Processing Fee")

		loan = make_line_of_credit_loan(self.applicant)
		sale = make_sale(loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 2000})
		sale.charges = 5000
		sell(sale, {"Test Security 2": (2000, 250)})
		sale.apply_proceeds()

		demand = frappe.db.get_value(
			"Loan Demand",
			{"loan": loan, "demand_type": "Charges", "demand_subtype": "Processing Fee", "docstatus": 1},
			["loan_disbursement", "outstanding_amount"],
			as_dict=True,
		)
		self.assertTrue(demand.loan_disbursement)
		self.assertEqual(flt(demand.outstanding_amount), 0)

	def test_sale_charge_needs_an_open_drawdown_on_a_line_of_credit(self):
		from unittest.mock import patch

		from lending.loan_management.doctype.loan_security_sale.proceeds import SaleProceeds
		from lending.tests.test_utils import add_or_update_loan_charges

		add_or_update_loan_charges("Term Loan Product 5")
		frappe.db.set_single_value("Lending Settings", "sale_charge", "Processing Fee")

		loan = make_line_of_credit_loan(self.applicant)
		sale = make_sale(loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 2000})
		sale.charges = 5000
		sell(sale, {"Test Security 2": (2000, 250)})

		# Every drawdown closed leaves nothing for the fee to ride on
		with patch.object(SaleProceeds, "get_disbursements", return_value=[]):
			with self.assertRaises(frappe.ValidationError):
				sale.apply_proceeds()
		self.assertFalse(frappe.db.exists("Loan Demand", {"loan": loan, "demand_type": "Charges"}))

	def test_moratorium_refuses_proceeds_that_do_not_close_the_loan(self):
		set_moratorium(self.loan, add_days(nowdate(), 90))
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 1000})
		sell(sale, {"Test Security 2": (1000, 200)})

		with self.assertRaises(frappe.ValidationError):
			sale.apply_proceeds()
		self.assertFalse(frappe.db.exists("Loan Repayment", {"reference_number": sale.name}))

	def test_moratorium_proceeds_are_applied_on_a_later_date(self):
		loan = make_line_of_credit_loan(self.applicant)
		set_moratorium(loan, add_days(nowdate(), -2))
		sale = make_sale(loan, reason="Loan Default")
		sale.posting_date = add_days(nowdate(), -5)
		sale.append("items", {"loan_security": "Test Security 2", "qty": 200})
		sell(sale, {"Test Security 2": (200, 250)})

		with self.assertRaises(frappe.ValidationError):
			sale.apply_proceeds()
		with self.assertRaises(frappe.ValidationError):
			sale.apply_proceeds(proceeds_date=add_days(nowdate(), 1))

		sale.apply_proceeds(proceeds_date=nowdate())
		sale.reload()
		self.assertEqual(str(sale.proceeds_date), nowdate())
		self.assertEqual(sale.repayments[0].repayment_type, "Pre Payment")
		self.assertEqual(
			str(frappe.db.get_value("Loan Repayment", sale.repayments[0].loan_repayment, "value_date"))[:10],
			nowdate(),
		)

	def test_moratorium_closes_the_loan_when_proceeds_cover_it(self):
		set_moratorium(self.loan, add_days(nowdate(), 90))
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 8000})
		sell(sale, {"Test Security 2": (8000, 250)})
		sale.apply_proceeds()
		sale.reload()

		self.assertEqual(sale.repayments[0].repayment_type, "Loan Closure")
		self.assertGreater(flt(sale.surplus_amount), 0)

	def test_moratorium_closure_accepts_the_write_off_shortfall(self):
		from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts

		set_moratorium(self.loan, add_days(nowdate(), 90))
		frappe.db.set_value("Loan Product", "Stock Loan", "write_off_amount", 100)
		self.addCleanup(frappe.db.set_value, "Loan Product", "Stock Loan", "write_off_amount", 0)

		closure = flt(calculate_amounts(self.loan, nowdate(), payment_type="Loan Closure")["payable_amount"])
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 1})
		sell(sale, {"Test Security 2": (1, closure - 50)})
		sale.apply_proceeds()
		sale.reload()

		self.assertEqual(sale.repayments[0].repayment_type, "Loan Closure")

	def test_release_without_a_loan_cannot_exceed_the_pledge(self):
		from lending.tests.test_utils import create_loan_security_release

		with self.assertRaises(frappe.ValidationError):
			create_loan_security_release(
				self.applicant, "Customer", [{"loan_security": "Test Security 2", "qty": 1000000}]
			)

	def test_sale_charge_is_demanded_from_the_borrower(self):
		from lending.tests.test_utils import add_or_update_loan_charges

		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 1000})
		sale.charges = 5000

		frappe.db.set_single_value("Lending Settings", "sale_charge", None)
		with self.assertRaises(frappe.ValidationError):
			sell(sale, {"Test Security 2": (1000, 200)})

		add_or_update_loan_charges("Stock Loan")
		frappe.db.set_single_value("Lending Settings", "sale_charge", "Processing Fee")
		sale.reload()
		sell(sale, {"Test Security 2": (1000, 200)})
		self.assertEqual(flt(sale.net_proceeds), 195000)

		sale.apply_proceeds()
		self.assertTrue(
			frappe.db.exists(
				"Loan Demand",
				{"loan": self.loan, "demand_type": "Charges", "demand_subtype": "Processing Fee"},
			)
		)

	def test_proceeds_apply_only_once(self):
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 1000})
		sell(sale, {"Test Security 2": (1000, 200)})

		# A second click carries the status the form loaded before the first one finished
		stale = frappe.get_doc("Loan Security Sale", sale.name)
		sale.apply_proceeds()
		with self.assertRaises(frappe.ValidationError):
			stale.apply_proceeds()
		self.assertEqual(frappe.db.count("Loan Repayment", {"reference_number": sale.name}), 1)

	def test_cancel_after_proceeds_reverses_repayment_and_charge(self):
		from lending.tests.test_utils import add_or_update_loan_charges

		add_or_update_loan_charges("Stock Loan")
		frappe.db.set_single_value("Lending Settings", "sale_charge", "Processing Fee")

		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 1000})
		sale.charges = 5000
		sell(sale, {"Test Security 2": (1000, 200)})
		sale.apply_proceeds()
		sale.reload()
		self.assertTrue(sale.charge_voucher)

		sale.cancel()
		self.assertEqual(
			frappe.db.get_value("Loan Repayment", sale.repayments[0].loan_repayment, "docstatus"), 2
		)
		self.assertEqual(frappe.db.get_value(sale.charge_voucher_type, sale.charge_voucher, "docstatus"), 2)

	def test_exposure_report_counts_the_sale(self):
		from lending.loan_management.report.applicant_wise_loan_security_exposure.applicant_wise_loan_security_exposure import (
			get_applicant_wise_total_loan_security_qty,
			get_loan_security_details,
		)

		def exposure():
			pledges, _total, _types = get_applicant_wise_total_loan_security_qty(
				{"company": "_Test Company"}, get_loan_security_details()
			)
			return flt(pledges.get((self.applicant, "Test Security 2")))

		before = exposure()
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 3000})
		sell(sale, {"Test Security 2": (3000, 200)})
		self.assertEqual(before - exposure(), 3000)

	def test_shortfall_must_belong_to_the_loan(self):
		set_price(200)
		create_process_loan_security_shortfall()
		shortfall = frappe.db.get_value("Loan Security Shortfall", {"loan": self.loan}, "name")

		other_loan = make_secured_loan(self.applicant, 4000)
		sale = make_sale(other_loan, loan_security_shortfall=shortfall)
		sale.append("items", {"loan_security": "Test Security 2", "qty": 100})
		with self.assertRaises(frappe.ValidationError):
			sale.insert()

	def test_cannot_sell_more_than_pledged(self):
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "sold_qty": 8001, "sale_price": 200})
		with self.assertRaises(frappe.ValidationError):
			sale.save()

	def test_release_cannot_be_approved_after_a_sale_consumed_its_collateral(self):
		from lending.loan_management.doctype.loan.loan import unpledge_security

		# At ₹500, 5,000 units left still allow ₹12,50,000 against ₹10,00,000 drawn
		set_price(500)
		release = unpledge_security(
			loan=self.loan, security_map={"Test Security 2": 3000}, save=1, submit=1
		)

		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 6000})
		sell(sale, {"Test Security 2": (6000, 500)})

		release.status = "Approved"
		with self.assertRaises(frappe.ValidationError):
			release.save()
		self.assertEqual(get_pledged_security_qty(loan=self.loan)["Test Security 2"], 2000)

	def test_cancel_returns_the_collateral(self):
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "qty": 8000})
		sell(sale, {"Test Security 2": (8000, 200)})

		sale.cancel()
		self.assertEqual(get_pledged_security_qty(loan=self.loan)["Test Security 2"], 8000)
		self.assertEqual(
			frappe.db.get_value("Loan Security Assignment", self.assignment, "status"), "Pledged"
		)


def set_price(price):
	create_loan_security_price(
		"Test Security 2", price, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
	)


def set_moratorium(loan, end_date):
	frappe.db.set_value(
		"Loan Repayment Schedule",
		{"loan": loan, "docstatus": 1, "status": "Active"},
		"moratorium_end_date",
		end_date,
	)


def make_line_of_credit_loan(applicant):
	"""A ₹5,00,000 credit line with two ₹1,00,000 drawdowns, secured by 4,000 units of security 2."""
	loan = create_loan(
		applicant,
		"Term Loan Product 5",
		500000,
		"Repay Over Number of Periods",
		12,
		repayment_start_date=add_days(nowdate(), 20),
		posting_date=add_days(nowdate(), -30),
		rate_of_interest=25,
		applicant_type="Customer",
		limit_applicable_start=add_days(nowdate(), -60),
		limit_applicable_end=add_days(nowdate(), 300),
	)
	loan.submit()
	for days_ago in (20, 10):
		make_loan_disbursement_entry(
			loan.name,
			100000,
			disbursement_date=add_days(nowdate(), -days_ago),
			repayment_start_date=add_days(nowdate(), 20),
		)
	create_loan_security_assignment(
		loan=loan.name, securities=[{"loan_security": "Test Security 2", "qty": 4000}]
	)
	return loan.name


def make_secured_loan(applicant, qty, disbursed_amount=None):
	pledges = [{"loan_security": "Test Security 2", "qty": qty, "haircut": 50}]
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


def make_sale(loan, reason="Margin Call Not Cured", loan_security_shortfall=None):
	sale = frappe.new_doc("Loan Security Sale")
	sale.loan = loan
	sale.reason = reason
	sale.loan_security_shortfall = loan_security_shortfall
	return sale


def sell(sale, sold):
	for row in sale.items:
		row.sold_qty, row.sale_price = sold[row.loan_security]
	sale.save()
	sale.submit()
