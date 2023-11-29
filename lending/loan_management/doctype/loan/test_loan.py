# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe
from frappe.utils import (
	add_days,
	add_months,
	add_to_date,
	date_diff,
	flt,
	format_date,
	get_datetime,
	nowdate,
)

from erpnext.selling.doctype.customer.test_customer import get_customer_dict
from erpnext.setup.doctype.employee.test_employee import make_employee

from lending.loan_management.doctype.loan.loan import (
	make_loan_write_off,
	request_loan_closure,
	unpledge_security,
)
from lending.loan_management.doctype.loan_application.loan_application import create_pledge
from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
	get_disbursal_amount,
)
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	days_in_year,
)
from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_security_unpledge.loan_security_unpledge import (
	get_pledged_security_qty,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_demand_loans,
	process_loan_interest_accrual_for_term_loans,
)
from lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall import (
	create_process_loan_security_shortfall,
)


class TestLoan(unittest.TestCase):
	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		simple_terms_loans = [
			["Personal Loan", 500000, 8.4, "Monthly as per repayment start date"],
			["Term Loan Product 1", 12000, 7.5, "Monthly as per repayment start date"],
		]

		pro_rated_term_loans = [
			["Term Loan Product 2", 12000, 7.5, "Pro-rated calendar months", "Start of the next month"],
			["Term Loan Product 3", 1200, 7.5, "Pro-rated calendar months", "End of the current month"],
		]

		for loan_product in simple_terms_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)

		for loan_product in pro_rated_term_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
				repayment_date_on=loan_product[4],
			)

		create_loan_product(
			"Stock Loan",
			"Stock Loan",
			2000000,
			13.5,
			25,
			1,
			5,
			"Cash",
			"Disbursement Account - _TC",
			"Payment Account - _TC",
			"Loan Account - _TC",
			"Interest Income Account - _TC",
			"Penalty Income Account - _TC",
			repayment_schedule_type="Monthly as per repayment start date",
		)

		create_loan_product(
			"Demand Loan",
			"Demand Loan",
			2000000,
			13.5,
			25,
			0,
			5,
			"Cash",
			"Disbursement Account - _TC",
			"Payment Account - _TC",
			"Loan Account - _TC",
			"Interest Income Account - _TC",
			"Penalty Income Account - _TC",
		)

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price(
			"Test Security 1", 500, "Nos", get_datetime(), get_datetime(add_to_date(nowdate(), hours=24))
		)
		create_loan_security_price(
			"Test Security 2", 250, "Nos", get_datetime(), get_datetime(add_to_date(nowdate(), hours=24))
		)

		self.applicant1 = make_employee("robert_loan@loan.com")
		if not frappe.db.exists("Customer", "_Test Loan Customer"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer")).insert(ignore_permissions=True)

		if not frappe.db.exists("Customer", "_Test Loan Customer 1"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer 1")).insert(ignore_permissions=True)

		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		self.applicant3 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer 1"}, "name")

	def test_loan(self):
		loan = create_loan(self.applicant1, "Personal Loan", 280000, "Repay Over Number of Periods", 20)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 0}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		self.assertEqual(loan_repayment_schedule.monthly_repayment_amount, 15052)
		self.assertEqual(flt(loan.total_interest_payable, 0), 21034)
		self.assertEqual(flt(loan.total_payment, 0), 301034)
		self.assertEqual(len(schedule), 20)

		for idx, principal_amount, interest_amount, balance_loan_amount in [
			[3, 13369, 1683, 227080],
			[19, 14941, 105, 0],
			[17, 14740, 312, 29785],
		]:
			self.assertEqual(flt(schedule[idx].principal_amount, 0), principal_amount)
			self.assertEqual(flt(schedule[idx].interest_amount, 0), interest_amount)
			self.assertEqual(flt(schedule[idx].balance_loan_amount, 0), balance_loan_amount)

		loan.repayment_method = "Repay Fixed Amount per Period"
		loan.monthly_repayment_amount = 14000
		loan.save()

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 0}
		)

		self.assertEqual(len(loan_repayment_schedule.repayment_schedule), 22)
		self.assertEqual(flt(loan.total_interest_payable, 0), 22712)
		self.assertEqual(flt(loan.total_payment, 0), 302712)

	def test_loan_with_security(self):
		pledge = [
			{
				"loan_security": "Test Security 1",
				"qty": 4000.00,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledge, "Repay Over Number of Periods", 12
		)
		create_pledge(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertEqual(loan.loan_amount, 1000000)

	def test_loan_disbursement(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledge, "Repay Over Number of Periods", 12
		)

		create_pledge(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertEqual(loan.loan_amount, 1000000)

		loan.submit()

		loan_disbursement_entry1 = make_loan_disbursement_entry(loan.name, 500000)
		loan_disbursement_entry2 = make_loan_disbursement_entry(loan.name, 500000)

		loan = frappe.get_doc("Loan", loan.name)
		gl_entries1 = frappe.db.get_all(
			"GL Entry",
			fields=["name"],
			filters={"voucher_type": "Loan Disbursement", "voucher_no": loan_disbursement_entry1.name},
		)

		gl_entries2 = frappe.db.get_all(
			"GL Entry",
			fields=["name"],
			filters={"voucher_type": "Loan Disbursement", "voucher_no": loan_disbursement_entry2.name},
		)

		self.assertEqual(loan.status, "Disbursed")
		self.assertEqual(loan.disbursed_amount, 1000000)
		self.assertTrue(gl_entries1)
		self.assertTrue(gl_entries2)

	def test_sanctioned_amount_limit(self):
		# Clear loan docs before checking
		frappe.db.sql("DELETE FROM `tabLoan` where applicant = '_Test Loan Customer 1'")
		frappe.db.sql("DELETE FROM `tabLoan Application` where applicant = '_Test Loan Customer 1'")
		frappe.db.sql("DELETE FROM `tabLoan Security Pledge` where applicant = '_Test Loan Customer 1'")

		if not frappe.db.get_value(
			"Sanctioned Loan Amount",
			filters={
				"applicant_type": "Customer",
				"applicant": "_Test Loan Customer 1",
				"company": "_Test Company",
			},
		):
			frappe.get_doc(
				{
					"doctype": "Sanctioned Loan Amount",
					"applicant_type": "Customer",
					"applicant": "_Test Loan Customer 1",
					"sanctioned_amount_limit": 1500000,
					"company": "_Test Company",
				}
			).insert(ignore_permissions=True)

		# Make First Loan
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant3, "Demand Loan", pledge
		)
		create_pledge(loan_application)
		loan = create_demand_loan(
			self.applicant3, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		# Make second loan greater than the sanctioned amount
		loan_application = create_loan_application(
			"_Test Company", self.applicant3, "Demand Loan", pledge, do_not_save=True
		)
		self.assertRaises(frappe.ValidationError, loan_application.save)

	def test_regular_loan_repayment(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		accrued_interest_amount = flt(
			(loan.loan_amount * loan.rate_of_interest * no_of_days)
			/ (days_in_year(get_datetime(first_date).year) * 100),
			2,
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)

		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

		repayment_entry = create_repayment_entry(
			loan.name, self.applicant2, add_days(last_date, 10), 111119
		)
		repayment_entry.save()
		repayment_entry.submit()

		penalty_amount = (accrued_interest_amount * 5 * 25) / (100 * 365)
		self.assertEqual(flt(repayment_entry.penalty_amount, 0), flt(penalty_amount, 0))

		amounts = frappe.db.get_all(
			"Loan Interest Accrual", {"loan": loan.name}, ["paid_interest_amount"]
		)

		loan.load_from_db()

		total_interest_paid = amounts[0]["paid_interest_amount"] + amounts[1]["paid_interest_amount"]
		self.assertEqual(amounts[1]["paid_interest_amount"], repayment_entry.interest_payable)
		self.assertEqual(
			flt(loan.total_principal_paid, 0),
			flt(repayment_entry.amount_paid - penalty_amount - total_interest_paid, 0),
		)

		# Check Repayment Entry cancel
		repayment_entry.load_from_db()
		repayment_entry.cancel()

		loan.load_from_db()
		self.assertEqual(loan.total_principal_paid, 0)
		self.assertEqual(loan.total_principal_paid, 0)

	def test_loan_closure(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		# Adding 5 since repayment is made 5 days late after due date
		# and since payment type is loan closure so interest should be considered for those
		# 5 days as well though in grace period
		no_of_days += 5

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

		repayment_entry = create_repayment_entry(
			loan.name,
			self.applicant2,
			add_days(last_date, 5),
			flt(loan.loan_amount + accrued_interest_amount),
		)

		repayment_entry.submit()

		amount = frappe.db.get_value(
			"Loan Interest Accrual", {"loan": loan.name}, ["sum(paid_interest_amount)"]
		)

		self.assertEqual(flt(amount, 0), flt(accrued_interest_amount, 0))
		self.assertEqual(flt(repayment_entry.penalty_amount, 5), 0)

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

	def test_loan_repayment_for_term_loan(self):
		pledges = [
			{"loan_security": "Test Security 2", "qty": 4000.00},
			{"loan_security": "Test Security 1", "qty": 2000.00},
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)
		create_pledge(loan_application)

		loan = create_loan_with_security(
			self.applicant2,
			"Stock Loan",
			"Repay Over Number of Periods",
			12,
			loan_application,
			posting_date=add_months(nowdate(), -1),
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date=add_months(nowdate(), -1)
		)

		process_loan_interest_accrual_for_term_loans(posting_date=nowdate())

		repayment_entry = create_repayment_entry(
			loan.name, self.applicant2, add_days(nowdate(), 5), 89768.75
		)

		repayment_entry.submit()

		amounts = frappe.db.get_value(
			"Loan Interest Accrual", {"loan": loan.name}, ["paid_interest_amount", "paid_principal_amount"]
		)

		self.assertEqual(amounts[0], 11250.00)
		self.assertEqual(amounts[1], 78303.00)

	def test_security_shortfall(self):
		pledges = [
			{
				"loan_security": "Test Security 2",
				"qty": 8000.00,
				"haircut": 50,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)

		create_pledge(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()

		make_loan_disbursement_entry(loan.name, loan.loan_amount)

		frappe.db.sql(
			"""UPDATE `tabLoan Security Price` SET loan_security_price = 100
			where loan_security='Test Security 2'"""
		)

		create_process_loan_security_shortfall()
		loan_security_shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})
		self.assertTrue(loan_security_shortfall)

		self.assertEqual(flt(loan_security_shortfall.loan_amount, 2), 1000000.00)
		self.assertEqual(flt(loan_security_shortfall.security_value, 2), 800000.00)
		self.assertEqual(flt(loan_security_shortfall.shortfall_amount, 2), 600000.00)

		frappe.db.sql(
			""" UPDATE `tabLoan Security Price` SET loan_security_price = 250
			where loan_security='Test Security 2'"""
		)

		create_process_loan_security_shortfall()
		loan_security_shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})
		self.assertEqual(loan_security_shortfall.status, "Completed")
		self.assertEqual(loan_security_shortfall.shortfall_amount, 0)

	def test_loan_security_unpledge(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		no_of_days += 5

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

		repayment_entry = create_repayment_entry(
			loan.name,
			self.applicant2,
			add_days(last_date, 5),
			flt(loan.loan_amount + accrued_interest_amount),
		)
		repayment_entry.submit()

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

		unpledge_request = unpledge_security(loan=loan.name, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		loan.load_from_db()

		pledged_qty = get_pledged_security_qty(loan.name)

		self.assertEqual(loan.status, "Closed")
		self.assertEqual(sum(pledged_qty.values()), 0)

		amounts = amounts = calculate_amounts(loan.name, add_days(last_date, 5))
		self.assertEqual(amounts["pending_principal_amount"], 0)
		self.assertEqual(amounts["payable_principal_amount"], 0.0)
		self.assertEqual(amounts["interest_amount"], 0)

	def test_partial_loan_security_unpledge(self):
		pledge = [
			{"loan_security": "Test Security 1", "qty": 2000.00},
			{"loan_security": "Test Security 2", "qty": 4000.00},
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

		repayment_entry = create_repayment_entry(
			loan.name, self.applicant2, add_days(last_date, 5), 600000
		)
		repayment_entry.submit()

		unpledge_map = {"Test Security 2": 2000}

		unpledge_request = unpledge_security(loan=loan.name, security_map=unpledge_map, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		unpledge_request.submit()
		unpledge_request.load_from_db()
		self.assertEqual(unpledge_request.docstatus, 1)

	def test_sanctioned_loan_security_unpledge(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		unpledge_map = {"Test Security 1": 4000}
		unpledge_request = unpledge_security(loan=loan.name, security_map=unpledge_map, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		unpledge_request.submit()

	def test_disbursal_check_with_shortfall(self):
		pledges = [
			{
				"loan_security": "Test Security 2",
				"qty": 8000.00,
				"haircut": 50,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)

		create_pledge(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()

		# Disbursing 7,00,000 from the allowed 10,00,000 according to security pledge
		make_loan_disbursement_entry(loan.name, 700000)

		frappe.db.sql(
			"""UPDATE `tabLoan Security Price` SET loan_security_price = 100
			where loan_security='Test Security 2'"""
		)

		create_process_loan_security_shortfall()
		loan_security_shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})
		self.assertTrue(loan_security_shortfall)

		self.assertEqual(get_disbursal_amount(loan.name), 0)

		frappe.db.sql(
			""" UPDATE `tabLoan Security Price` SET loan_security_price = 250
			where loan_security='Test Security 2'"""
		)

	def test_disbursal_check_without_shortfall(self):
		pledges = [
			{
				"loan_security": "Test Security 2",
				"qty": 8000.00,
				"haircut": 50,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)

		create_pledge(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()

		# Disbursing 7,00,000 from the allowed 10,00,000 according to security pledge
		make_loan_disbursement_entry(loan.name, 700000)

		self.assertEqual(get_disbursal_amount(loan.name), 300000)

	def test_pending_loan_amount_after_closure_request(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		no_of_days += 5

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))

		repayment_entry = create_repayment_entry(
			loan.name,
			self.applicant2,
			add_days(last_date, 5),
			flt(loan.loan_amount + accrued_interest_amount),
		)
		repayment_entry.submit()

		amounts = frappe.db.get_value(
			"Loan Interest Accrual", {"loan": loan.name}, ["paid_interest_amount", "paid_principal_amount"]
		)

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))
		self.assertEqual(amounts["pending_principal_amount"], 0.0)

	def test_partial_unaccrued_interest_payment(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		no_of_days += 5

		# get partial unaccrued interest amount
		paid_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))

		repayment_entry = create_repayment_entry(
			loan.name, self.applicant2, add_days(last_date, 5), paid_amount
		)

		repayment_entry.submit()
		repayment_entry.load_from_db()

		partial_accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * 5) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		interest_amount = flt(amounts["interest_amount"] + partial_accrued_interest_amount, 2)
		self.assertEqual(flt(repayment_entry.total_interest_paid, 0), flt(interest_amount, 0))

	def test_penalty(self):
		loan, amounts = create_loan_scenario_for_penalty(self)
		# 30 days - grace period
		penalty_days = 30 - 4
		penalty_applicable_amount = flt(amounts["interest_amount"] / 2)
		penalty_amount = flt((((penalty_applicable_amount * 25) / (100 * 365)) * penalty_days), 2)
		process = process_loan_interest_accrual_for_demand_loans(posting_date="2019-11-30")

		calculated_penalty_amount = frappe.db.get_value(
			"Loan Interest Accrual",
			{"process_loan_interest_accrual": process, "loan": loan.name},
			"penalty_amount",
		)

		self.assertEqual(loan.loan_amount, 1000000)
		self.assertEqual(calculated_penalty_amount, penalty_amount)

	def test_loan_write_off_limit(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1
		no_of_days += 5

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

		# repay 50 less so that it can be automatically written off
		repayment_entry = create_repayment_entry(
			loan.name,
			self.applicant2,
			add_days(last_date, 5),
			flt(loan.loan_amount + accrued_interest_amount - 50),
		)

		repayment_entry.submit()

		amount = frappe.db.get_value(
			"Loan Interest Accrual", {"loan": loan.name}, ["sum(paid_interest_amount)"]
		)

		self.assertEqual(flt(amount, 0), flt(accrued_interest_amount, 0))
		self.assertEqual(flt(repayment_entry.penalty_amount, 5), 0)

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))
		self.assertEqual(flt(amounts["pending_principal_amount"], 0), 50)

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

	def test_loan_repayment_against_partially_disbursed_loan(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		make_loan_disbursement_entry(loan.name, loan.loan_amount / 2, disbursement_date=first_date)

		loan.load_from_db()

		self.assertEqual(loan.status, "Partially Disbursed")
		create_repayment_entry(
			loan.name, self.applicant2, add_days(last_date, 5), flt(loan.loan_amount / 3)
		)

	def test_loan_amount_write_off(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_pledge(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1
		no_of_days += 5

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

		# repay 100 less so that it can be automatically written off
		repayment_entry = create_repayment_entry(
			loan.name,
			self.applicant2,
			add_days(last_date, 5),
			flt(loan.loan_amount + accrued_interest_amount - 100),
		)

		repayment_entry.submit()

		amount = frappe.db.get_value(
			"Loan Interest Accrual", {"loan": loan.name}, ["sum(paid_interest_amount)"]
		)

		self.assertEqual(flt(amount, 0), flt(accrued_interest_amount, 0))
		self.assertEqual(flt(repayment_entry.penalty_amount, 5), 0)

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))
		self.assertEqual(flt(amounts["pending_principal_amount"], 0), 100)

		we = make_loan_write_off(loan.name, amount=amounts["pending_principal_amount"])
		we.submit()

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))
		self.assertEqual(flt(amounts["pending_principal_amount"], 0), 0)

	def test_term_loan_schedule_types(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 1",
			12000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2022-10-17",
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 0}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		# Check for first, second and last installment date
		self.assertEqual(format_date(schedule[0].payment_date, "dd-MM-yyyy"), "17-10-2022")
		self.assertEqual(format_date(schedule[1].payment_date, "dd-MM-yyyy"), "17-11-2022")
		self.assertEqual(format_date(schedule[-1].payment_date, "dd-MM-yyyy"), "17-09-2023")

		loan.loan_product = "Term Loan Product 2"
		loan.save()

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 0}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		# Check for first, second and last installment date
		self.assertEqual(format_date(schedule[0].payment_date, "dd-MM-yyyy"), "01-11-2022")
		self.assertEqual(format_date(schedule[1].payment_date, "dd-MM-yyyy"), "01-12-2022")
		self.assertEqual(format_date(schedule[-1].payment_date, "dd-MM-yyyy"), "01-10-2023")

		loan.loan_product = "Term Loan Product 3"
		loan.save()

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 0}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		# Check for first, second and last installment date
		self.assertEqual(format_date(schedule[0].payment_date, "dd-MM-yyyy"), "31-10-2022")
		self.assertEqual(format_date(schedule[1].payment_date, "dd-MM-yyyy"), "30-11-2022")
		self.assertEqual(format_date(schedule[-1].payment_date, "dd-MM-yyyy"), "30-09-2023")

		loan.repayment_method = "Repay Fixed Amount per Period"
		loan.monthly_repayment_amount = 1042
		loan.save()

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 0}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		self.assertEqual(format_date(schedule[0].payment_date, "dd-MM-yyyy"), "31-10-2022")
		self.assertEqual(format_date(schedule[1].payment_date, "dd-MM-yyyy"), "30-11-2022")
		self.assertEqual(format_date(schedule[-1].payment_date, "dd-MM-yyyy"), "30-09-2023")


def create_loan_scenario_for_penalty(doc):
	pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

	loan_application = create_loan_application("_Test Company", doc.applicant2, "Demand Loan", pledge)
	create_pledge(loan_application)
	loan = create_demand_loan(
		doc.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
	)
	loan.submit()

	first_date = "2019-10-01"
	last_date = "2019-10-30"

	make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
	process_loan_interest_accrual_for_demand_loans(posting_date=last_date)

	amounts = calculate_amounts(loan.name, add_days(last_date, 1))
	paid_amount = amounts["interest_amount"] / 2

	repayment_entry = create_repayment_entry(
		loan.name, doc.applicant2, add_days(last_date, 5), paid_amount
	)

	repayment_entry.submit()

	return loan, amounts


def create_loan_accounts():
	create_account(
		"Loans and Advances (Assets)",
		"Current Assets - _TC",
		"Asset",
		"Bank",
		"Balance Sheet",
		is_group=1,
	)
	create_account(
		"Loan Account", "Loans and Advances (Assets) - _TC", "Asset", "Bank", "Balance Sheet"
	)
	create_account("Payment Account", "Bank Accounts - _TC", "Asset", "Bank", "Balance Sheet")
	create_account("Disbursement Account", "Bank Accounts - _TC", "Asset", "Bank", "Balance Sheet")
	create_account(
		"Interest Income Account", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)
	create_account(
		"Penalty Income Account", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)
	create_account(
		"Interest Receivable",
		"Loans and Advances (Assets) - _TC",
		"Asset",
		"Receivable",
		"Balance Sheet",
	)
	create_account(
		"Charges Receivable", "Loans and Advances (Assets) - _TC", "Asset", "Receivable", "Balance Sheet"
	)
	create_account(
		"Penalty Receivable", "Loans and Advances (Assets) - _TC", "Asset", "Receivable", "Balance Sheet"
	)
	create_account(
		"Suspense Interest Receivable",
		"Loans and Advances (Assets) - _TC",
		"Asset",
		"Receivable",
		"Balance Sheet",
	)
	create_account(
		"Suspense Income Account", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)


def create_account(account_name, parent_account, root_type, account_type, report_type, is_group=0):
	if not frappe.db.exists("Account", {"account_name": account_name}):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"company": "_Test Company",
				"root_type": root_type,
				"report_type": report_type,
				"currency": "INR",
				"parent_account": parent_account,
				"account_type": account_type,
				"is_group": is_group,
			}
		).insert(ignore_permissions=True)


def create_loan_product(
	product_code,
	product_name,
	maximum_loan_amount,
	rate_of_interest,
	penalty_interest_rate=None,
	is_term_loan=1,
	grace_period_in_days=None,
	disbursement_account="Disbursement Account - _TC",
	payment_account="Payment Account - _TC",
	loan_account="Loan Account - _TC",
	interest_income_account="Interest Income Account - _TC",
	penalty_income_account="Penalty Income Account - _TC",
	interest_receivable_account="Interest Receivable - _TC",
	penalty_receivable_account="Penalty Receivable - _TC",
	charges_receivable_account="Charges Receivable - _TC",
	suspense_interest_receivable="Suspense Interest Receivable - _TC",
	suspense_interest_income="Suspense Income Account - _TC",
	repayment_method=None,
	repayment_periods=None,
	repayment_schedule_type=None,
	repayment_date_on=None,
	days_past_due_threshold_for_npa=None,
	min_days_bw_disbursement_first_repayment=None,
):

	if not frappe.db.exists("Loan Product", product_code):
		loan_product = frappe.get_doc(
			{
				"doctype": "Loan Product",
				"company": "_Test Company",
				"product_code": product_code,
				"product_name": product_name,
				"is_term_loan": is_term_loan,
				"repayment_schedule_type": "Monthly as per repayment start date",
				"maximum_loan_amount": maximum_loan_amount,
				"rate_of_interest": rate_of_interest,
				"penalty_interest_rate": penalty_interest_rate,
				"grace_period_in_days": grace_period_in_days,
				"disbursement_account": disbursement_account,
				"payment_account": payment_account,
				"loan_account": loan_account,
				"interest_income_account": interest_income_account,
				"penalty_income_account": penalty_income_account,
				"interest_receivable_account": interest_receivable_account,
				"penalty_receivable_account": penalty_receivable_account,
				"charges_receivable_account": charges_receivable_account,
				"suspense_interest_receivable": suspense_interest_receivable,
				"suspense_interest_income": suspense_interest_income,
				"repayment_method": repayment_method,
				"repayment_periods": repayment_periods,
				"write_off_amount": 100,
				"days_past_due_threshold_for_npa": days_past_due_threshold_for_npa,
				"min_days_bw_disbursement_first_repayment": min_days_bw_disbursement_first_repayment,
				"min_auto_closure_tolerance_amount": -100,
				"max_auto_closure_tolerance_amount": 100,
			}
		)

		if loan_product.is_term_loan:
			loan_product.repayment_schedule_type = repayment_schedule_type
			if loan_product.repayment_schedule_type != "Monthly as per repayment start date":
				loan_product.repayment_date_on = repayment_date_on

		loan_product.insert()

		return loan_product


def create_loan_security_type():
	if not frappe.db.exists("Loan Security Type", "Stock"):
		frappe.get_doc(
			{
				"doctype": "Loan Security Type",
				"loan_security_type": "Stock",
				"unit_of_measure": "Nos",
				"haircut": 50.00,
				"loan_to_value_ratio": 50,
			}
		).insert(ignore_permissions=True)


def create_loan_security():
	if not frappe.db.exists("Loan Security", "Test Security 1"):
		frappe.get_doc(
			{
				"doctype": "Loan Security",
				"loan_security_type": "Stock",
				"loan_security_code": "532779",
				"loan_security_name": "Test Security 1",
				"unit_of_measure": "Nos",
				"haircut": 50.00,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Loan Security", "Test Security 2"):
		frappe.get_doc(
			{
				"doctype": "Loan Security",
				"loan_security_type": "Stock",
				"loan_security_code": "531335",
				"loan_security_name": "Test Security 2",
				"unit_of_measure": "Nos",
				"haircut": 50.00,
			}
		).insert(ignore_permissions=True)


def create_loan_security_pledge(applicant, pledges, loan_application=None, loan=None):

	lsp = frappe.new_doc("Loan Security Pledge")
	lsp.applicant_type = "Customer"
	lsp.applicant = applicant
	lsp.company = "_Test Company"
	lsp.loan_application = loan_application

	if loan:
		lsp.loan = loan

	for pledge in pledges:
		lsp.append("securities", {"loan_security": pledge["loan_security"], "qty": pledge["qty"]})

	lsp.save()
	lsp.submit()

	return lsp


def make_loan_disbursement_entry(loan, amount, disbursement_date=None):

	loan_disbursement_entry = frappe.get_doc(
		{
			"doctype": "Loan Disbursement",
			"against_loan": loan,
			"disbursement_date": disbursement_date,
			"company": "_Test Company",
			"disbursed_amount": amount,
			"cost_center": "Main - _TC",
		}
	).insert(ignore_permissions=True)

	loan_disbursement_entry.save()
	loan_disbursement_entry.submit()

	return loan_disbursement_entry


def create_loan_security_price(loan_security, loan_security_price, uom, from_date, to_date):

	if not frappe.db.get_value(
		"Loan Security Price",
		{"loan_security": loan_security, "valid_from": ("<=", from_date), "valid_upto": (">=", to_date)},
		"name",
	):

		lsp = frappe.get_doc(
			{
				"doctype": "Loan Security Price",
				"loan_security": loan_security,
				"loan_security_price": loan_security_price,
				"uom": uom,
				"valid_from": from_date,
				"valid_upto": to_date,
			}
		).insert(ignore_permissions=True)


def create_repayment_entry(loan, applicant, posting_date, paid_amount, offset_based_on_npa=0):
	lr = frappe.get_doc(
		{
			"doctype": "Loan Repayment",
			"against_loan": loan,
			"company": "_Test Company",
			"posting_date": posting_date or nowdate(),
			"applicant": applicant,
			"amount_paid": paid_amount,
			"loan_product": "Stock Loan",
			"offset_based_on_npa": offset_based_on_npa,
		}
	).insert(ignore_permissions=True)

	return lr


def create_loan_application(
	company,
	applicant,
	loan_product,
	proposed_pledges,
	repayment_method=None,
	repayment_periods=None,
	posting_date=None,
	do_not_save=False,
):
	loan_application = frappe.new_doc("Loan Application")
	loan_application.applicant_type = "Customer"
	loan_application.company = company
	loan_application.applicant = applicant
	loan_application.loan_product = loan_product
	loan_application.posting_date = posting_date or nowdate()
	loan_application.is_secured_loan = 1

	if repayment_method:
		loan_application.repayment_method = repayment_method
		loan_application.repayment_periods = repayment_periods

	for pledge in proposed_pledges:
		loan_application.append("proposed_pledges", pledge)

	if do_not_save:
		return loan_application

	loan_application.save()
	loan_application.submit()

	loan_application.status = "Approved"
	loan_application.save()

	return loan_application.name


def create_loan(
	applicant,
	loan_product,
	loan_amount,
	repayment_method,
	repayment_periods,
	applicant_type=None,
	repayment_start_date=None,
	posting_date=None,
):

	loan = frappe.get_doc(
		{
			"doctype": "Loan",
			"applicant_type": applicant_type or "Employee",
			"company": "_Test Company",
			"applicant": applicant,
			"loan_product": loan_product,
			"loan_amount": loan_amount,
			"repayment_method": repayment_method,
			"repayment_periods": repayment_periods,
			"repayment_start_date": repayment_start_date or nowdate(),
			"posting_date": posting_date or nowdate(),
		}
	)

	loan.save()
	return loan


def create_loan_with_security(
	applicant,
	loan_product,
	repayment_method,
	repayment_periods,
	loan_application,
	posting_date=None,
	repayment_start_date=None,
):
	loan = frappe.get_doc(
		{
			"doctype": "Loan",
			"company": "_Test Company",
			"applicant_type": "Customer",
			"posting_date": posting_date or nowdate(),
			"loan_application": loan_application,
			"applicant": applicant,
			"loan_product": loan_product,
			"is_term_loan": 1,
			"is_secured_loan": 1,
			"repayment_method": repayment_method,
			"repayment_periods": repayment_periods,
			"repayment_start_date": repayment_start_date or nowdate(),
			"payment_account": "Payment Account - _TC",
			"loan_account": "Loan Account - _TC",
			"interest_income_account": "Interest Income Account - _TC",
			"penalty_income_account": "Penalty Income Account - _TC",
		}
	)

	loan.save()

	return loan


def create_demand_loan(applicant, loan_product, loan_application, posting_date=None):

	loan = frappe.get_doc(
		{
			"doctype": "Loan",
			"company": "_Test Company",
			"applicant_type": "Customer",
			"posting_date": posting_date or nowdate(),
			"loan_application": loan_application,
			"applicant": applicant,
			"loan_product": loan_product,
			"is_term_loan": 0,
			"is_secured_loan": 1,
			"payment_account": "Payment Account - _TC",
			"loan_account": "Loan Account - _TC",
			"interest_income_account": "Interest Income Account - _TC",
			"penalty_income_account": "Penalty Income Account - _TC",
		}
	)

	loan.save()

	return loan


def set_loan_settings_in_company(company=None):
	if not company:
		company = "_Test Company"
	company = frappe.get_doc("Company", company)
	company.min_days_bw_disbursement_first_repayment = 15
	company.save()
