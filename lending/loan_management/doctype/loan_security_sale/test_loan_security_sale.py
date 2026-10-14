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
		self.assertEqual(frappe.db.get_value("Loan Repayment", sale.loan_repayment, "amount_paid"), 400000)
		self.assertEqual(flt(sale.surplus_amount), 0)

		create_process_loan_security_shortfall()
		self.assertEqual(frappe.db.get_value("Loan Security Shortfall", shortfall.name, "status"), "Completed")

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
		amount_paid = flt(frappe.db.get_value("Loan Repayment", sale.loan_repayment, "amount_paid"))
		self.assertGreaterEqual(amount_paid, 1000000)
		self.assertEqual(flt(sale.surplus_amount, 2), flt(1600000 - amount_paid, 2))

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
		self.assertEqual(frappe.db.get_value("Loan Repayment", sale.loan_repayment, "docstatus"), 2)
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

	def test_cannot_sell_more_than_pledged(self):
		sale = make_sale(self.loan, reason="Loan Default")
		sale.append("items", {"loan_security": "Test Security 2", "sold_qty": 8001, "sale_price": 200})
		with self.assertRaises(frappe.ValidationError):
			sale.save()

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


def make_secured_loan(applicant, qty):
	pledges = [{"loan_security": "Test Security 2", "qty": qty, "haircut": 50}]
	loan_application = create_loan_application(
		"_Test Company", applicant, "Stock Loan", pledges, "Repay Over Number of Periods", 12
	)
	create_loan_security_assignment(loan_application)
	loan = create_loan_with_security(
		applicant, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
	)
	loan.submit()
	make_loan_disbursement_entry(loan.name, loan.loan_amount)
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
