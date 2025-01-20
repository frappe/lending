# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest
from datetime import datetime

import frappe
from frappe.utils import (
	add_days,
	add_months,
	add_to_date,
	date_diff,
	flt,
	get_datetime,
	getdate,
	nowdate,
)

from erpnext.selling.doctype.customer.test_customer import get_customer_dict
from erpnext.setup.doctype.employee.test_employee import make_employee

from lending.loan_management.doctype.loan.loan import (
	make_loan_write_off,
	request_loan_closure,
	unpledge_security,
)
from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
	get_disbursal_amount,
)
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	days_in_year,
)
from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)
from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
	create_process_loan_classification,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall import (
	create_process_loan_security_shortfall,
)


class TestLoan(unittest.TestCase):
	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()

		simple_terms_loans = [
			["Personal Loan", 500000, 8.4, "Monthly as per repayment start date"],
			["Term Loan Product 1", 12000, 7.5, "Monthly as per repayment start date"],
		]

		pro_rated_term_loans = [
			["Term Loan Product 2", 12000, 7.5, "Pro-rated calendar months", "Start of the next month"],
			["Term Loan Product 3", 1200, 25, "Pro-rated calendar months", "End of the current month"],
		]

		cyclic_date_term_loans = [
			["Term Loan Product 4", 3000000, 25, "Monthly as per cycle date"],
		]

		loc_loans = [
			["Term Loan Product 5", 3000000, 25, "Line of Credit"],
		]

		for loan_product in simple_terms_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)

		for loan_product in cyclic_date_term_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)

		for loan_product in loc_loans:
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
			"Cash - _TC",
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
			"Cash - _TC",
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

		frappe.db.set_value(
			"Loan Product", "Demand Loan", "customer_refund_account", "Customer Refund Account - _TC"
		)

	def test_loan_with_repayment_periods(self):
		loan = create_loan(
			self.applicant1,
			"Personal Loan",
			280000,
			"Repay Over Number of Periods",
			repayment_periods=20,
			repayment_start_date=add_months(nowdate(), 1),
		)

		loan.submit()

		make_loan_disbursement_entry(loan.name, 280000, repayment_start_date=add_months(nowdate(), 1))

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		loan.load_from_db()
		self.assertEqual(loan_repayment_schedule.monthly_repayment_amount, 15052)
		self.assertEqual(flt(loan.total_interest_payable, 0), 21033)
		self.assertEqual(flt(loan.total_payment, 0), 301033)
		self.assertEqual(len(schedule), 20)

		for idx, principal_amount, interest_amount, balance_loan_amount in [
			[3, 13336, 1716, 227159],
			[19, 14938, 107, 0],
			[17, 14734, 318, 29784],
		]:
			self.assertEqual(flt(schedule[idx].principal_amount, 0), principal_amount)
			self.assertEqual(flt(schedule[idx].interest_amount, 0), interest_amount)
			self.assertEqual(flt(schedule[idx].balance_loan_amount, 0), balance_loan_amount)

	def test_loan_with_fixed_amount_per_period(self):
		loan = create_loan(
			self.applicant1,
			"Personal Loan",
			280000,
			"Repay Over Number of Periods",
			repayment_periods=20,
			repayment_start_date=add_months(nowdate(), 1),
		)

		loan.repayment_method = "Repay Fixed Amount per Period"
		loan.monthly_repayment_amount = 14000
		loan.submit()

		make_loan_disbursement_entry(loan.name, 280000, repayment_start_date=add_months(nowdate(), 1))

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)

		loan.load_from_db()
		self.assertEqual(len(loan_repayment_schedule.repayment_schedule), 22)
		self.assertEqual(flt(loan.total_interest_payable, 0), 22708)
		self.assertEqual(flt(loan.total_payment, 0), 302708)

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
		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertEqual(loan.loan_amount, 1000000)

	def test_loan_disbursement(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledge, "Repay Over Number of Periods", 12
		)

		create_loan_security_assignment(loan_application)

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
		frappe.db.sql(
			"DELETE FROM `tabLoan Security Assignment` where applicant = '_Test Loan Customer 1'"
		)

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
		create_loan_security_assignment(loan_application)
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
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date)

		accrued_interest_amount = flt(
			(loan.loan_amount * loan.rate_of_interest * no_of_days)
			/ (days_in_year(get_datetime(first_date).year) * 100),
			2,
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(posting_date=last_date)

		process_loan_interest_accrual_for_loans(posting_date=add_days(last_date, 10))

		repayment_entry = create_repayment_entry(loan.name, add_days(last_date, 10), 111119)
		repayment_entry.save()
		repayment_entry.submit()

		penalty_amount = (accrued_interest_amount * 5 * 25) / (100 * 365)
		self.assertEqual(flt(repayment_entry.penalty_amount, 0), flt(penalty_amount, 0))

		amounts = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "demand_type": "Normal", "demand_subtype": "Interest"},
			["SUM(paid_amount) as paid_amount", "SUM(demand_amount) as payable_amount"],
		)

		loan.load_from_db()
		total_interest_paid = flt(amounts[0]["paid_amount"], 2)
		self.assertEqual(flt(amounts[0]["payable_amount"], 2), repayment_entry.interest_payable)
		self.assertEqual(
			flt(loan.total_principal_paid, 0),
			flt(repayment_entry.amount_paid - penalty_amount - total_interest_paid, 0),
		)

		# # Check Repayment Entry cancel
		repayment_entry.load_from_db()
		repayment_entry.cancel()
		loan.load_from_db()

		self.assertEqual(loan.total_principal_paid, 0)

	def test_loan_closure(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)
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
		process_loan_interest_accrual_for_loans(posting_date=last_date)

		repayment_entry = create_repayment_entry(
			loan.name,
			add_days(last_date, 5),
			flt(loan.loan_amount + accrued_interest_amount),
		)

		repayment_entry.submit()

		amounts = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "demand_type": "Normal", "demand_subtype": "Interest"},
			["SUM(demand_amount) as payable_amount"],
		)

		self.assertEqual(flt(amounts[0].payable_amount, 0), flt(accrued_interest_amount, 0))
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
		create_loan_security_assignment(loan_application)

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
			loan.name,
			loan.loan_amount,
			disbursement_date=add_months(nowdate(), -1),
			repayment_start_date=nowdate(),
		)

		process_daily_loan_demands(loan=loan.name, posting_date=nowdate())

		repayment_entry = create_repayment_entry(loan.name, nowdate(), 89768.75)

		repayment_entry.submit()

		# amounts = frappe.db.get_value(
		# 	"Loan Interest Accrual", {"loan": loan.name}, ["paid_interest_amount", "paid_principal_amount"]
		# )

		amounts = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "demand_type": "EMI", "demand_subtype": "Interest"},
			["SUM(paid_amount) as paid_amount"],
		)

		self.assertEqual(amounts[0].paid_amount, 11465.75)
		self.assertEqual(repayment_entry.principal_amount_paid, 78303.00)

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

		create_loan_security_assignment(loan_application)

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

	def test_loan_security_release(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

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
		process_loan_interest_accrual_for_loans(posting_date=last_date)

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

	def test_partial_loan_security_release(self):
		pledge = [
			{"loan_security": "Test Security 1", "qty": 2000.00},
			{"loan_security": "Test Security 2", "qty": 4000.00},
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(posting_date=last_date)

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

	def test_sanctioned_loan_security_release(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

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

		create_loan_security_assignment(loan_application)

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

		create_loan_security_assignment(loan_application)

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
		create_loan_security_assignment(loan_application)

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
		process_loan_interest_accrual_for_loans(posting_date=last_date)

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
		# pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		# loan_application = create_loan_application(
		# 	"_Test Company", self.applicant2, "Demand Loan", pledge
		# )
		# create_loan_security_assignment(loan_application)

		# loan = create_demand_loan(
		# 	self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		# )
		# loan.submit()

		# self.assertEqual(loan.loan_amount, 1000000)

		# # get partial unaccrued interest amount

		# make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		# process_loan_interest_accrual_for_loans(posting_date=last_date)

		# amounts = calculate_amounts(loan.name, add_days(last_date, 5))

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		repayment_date = add_days("2019-10-30", 5)
		no_of_days = date_diff(repayment_date, add_days("2019-10-01", 1))

		loan = create_secured_demand_loan(self.applicant2)
		partial_accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * 5) / (
			days_in_year(get_datetime("2019-10-01").year) * 100
		)

		paid_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)
		repayment_entry = create_repayment_entry(loan.name, add_days(last_date, 5), paid_amount)

		repayment_entry.submit()
		repayment_entry.load_from_db()

		amounts = calculate_amounts(loan.name, add_days("2019-10-30", 5))
		interest_amount = flt(amounts["interest_amount"] + partial_accrued_interest_amount, 2)
		self.assertEqual(flt(repayment_entry.total_interest_paid, 0), flt(interest_amount, 0))

	def test_penalty(self):
		loan, amounts = create_loan_scenario_for_penalty(self)
		# 30 days - grace period
		penalty_days = 30 - 4
		penalty_applicable_amount = flt(amounts["interest_amount"] / 2)
		penalty_amount = flt((((penalty_applicable_amount * 25) / (100 * 365)) * penalty_days), 2)
		process = process_loan_interest_accrual_for_loans(posting_date="2019-11-30")

		calculated_penalty_amount = frappe.db.get_value(
			"Loan Interest Accrual",
			{"process_loan_interest_accrual": process, "loan": loan.name},
			"interest_amount",
		)

		self.assertEqual(loan.loan_amount, 1000000)
		self.assertEqual(calculated_penalty_amount, penalty_amount)

	def test_loan_write_off_limit(self):
		loan = create_secured_demand_loan(self.applicant2)
		self.assertEqual(loan.loan_amount, 1000000)
		repayment_date = add_days("2019-10-30", 5)
		no_of_days = date_diff(repayment_date, add_days("2019-10-01", 1))

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime("2019-10-01").year) * 100
		)

		# repay 50 less so that it can be automatically written off
		repayment_entry = create_repayment_entry(
			loan.name,
			repayment_date,
			flt(loan.loan_amount + accrued_interest_amount - 50),
		)

		repayment_entry.submit()

		amount = frappe.db.get_value(
			"Loan Demand",
			{"loan": loan.name, "demand_type": "Normal", "demand_subtype": "Interest"},
			["sum(demand_amount)"],
		)

		self.assertEqual(flt(amount, 0), flt(accrued_interest_amount, 0))
		self.assertEqual(flt(repayment_entry.penalty_amount, 5), 0)

		amounts = calculate_amounts(loan.name, add_days("2019-10-30", 5))
		self.assertEqual(flt(amounts["pending_principal_amount"], 0), 50)

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

	def test_loan_repayment_against_partially_disbursed_loan(self):
		loan = create_secured_demand_loan(self.applicant2, disbursement_amount=500000)
		loan.load_from_db()

		self.assertEqual(loan.status, "Partially Disbursed")
		create_repayment_entry(loan.name, add_days("2019-10-30", 5), flt(loan.loan_amount / 3))

	# def test_loan_auto_write_off_limit(self):
	# 	loan = create_secured_demand_loan(self.applicant2)

	# 	self.assertEqual(loan.loan_amount, 1000000)

	# 	repayment_date = add_days("2019-10-30", 5)
	# 	no_of_days = date_diff(repayment_date, add_days("2019-10-01", 1))

	# 	accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
	# 		days_in_year(get_datetime("2019-10-01").year) * 100
	# 	)
	# 	# repay 100 less so that it can be automatically written off
	# 	repayment_entry = create_repayment_entry(
	# 		loan.name,
	# 		repayment_date,
	# 		flt(loan.loan_amount + accrued_interest_amount - 100),
	# 	)

	# 	repayment_entry.submit()

	# 	amount = frappe.db.get_value(
	# 		"Loan Demand",
	# 		{"loan": loan.name, "demand_type": "Normal", "demand_subtype": "Interest"},
	# 		["sum(demand_amount)"],
	# 	)

	# 	self.assertEqual(flt(amount, 0), flt(accrued_interest_amount, 0))
	# 	self.assertEqual(flt(repayment_entry.penalty_amount, 5), 0)

	# 	amounts = calculate_amounts(loan.name, repayment_date)
	# 	self.assertEqual(flt(amounts["pending_principal_amount"], 0), 100)

	# 	we = make_loan_write_off(loan.name, amount=amounts["pending_principal_amount"])
	# 	we.submit()

	# 	amounts = calculate_amounts(loan.name, repayment_date)
	# 	self.assertEqual(flt(amounts["pending_principal_amount"], 0), 0)

	def test_term_loan_schedule_types(self):
		def _create_loan_for_schedule(loan_product, repayment_method, monthly_repayment_amount=None):
			loan = create_loan(
				self.applicant1,
				loan_product,
				12000,
				repayment_method,
				12,
				repayment_start_date="2022-10-17",
				monthly_repayment_amount=monthly_repayment_amount,
			)

			loan.posting_date = "2022-10-17"
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=loan.posting_date,
				repayment_start_date="2022-10-17",
			)

			loan_repayment_schedule = frappe.get_doc("Loan Repayment Schedule", {"loan": loan.name})
			schedule = loan_repayment_schedule.repayment_schedule

			return schedule

		schedule = _create_loan_for_schedule("Term Loan Product 1", "Repay Over Number of Periods")

		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-17"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-17"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-17"))

		schedule = _create_loan_for_schedule("Term Loan Product 2", "Repay Over Number of Periods")
		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-11-01"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-12-01"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-10-01"))

		schedule = _create_loan_for_schedule("Term Loan Product 3", "Repay Over Number of Periods")
		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-31"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-30"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-30"))

		schedule = _create_loan_for_schedule(
			"Term Loan Product 3", "Repay Fixed Amount per Period", monthly_repayment_amount=1042
		)
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-31"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-30"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-30"))

	def test_advance_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-01",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-04-01", repayment_start_date="2024-05-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 47523)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-29", 47523, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		lrs = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)
		self.assertEqual(lrs.monthly_repayment_amount, 47523)
		self.assertEqual(lrs.get("repayment_schedule")[3].total_payment, 47523)
		self.assertEqual(lrs.broken_period_interest, 0)
		self.assertEqual(lrs.broken_period_interest_days, 0)

	def test_multi_tranche_disbursement_accrual(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-18",
			rate_of_interest=23,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			500000,
			disbursement_date=getdate("2024-04-18"),
			repayment_start_date=getdate("2024-05-05"),
		)

		make_loan_disbursement_entry(
			loan.name,
			300000,
			disbursement_date=getdate("2024-05-10"),
			repayment_start_date=getdate("2024-06-05"),
		)

		make_loan_disbursement_entry(
			loan.name,
			200000,
			disbursement_date=getdate("2024-06-10"),
			repayment_start_date=getdate("2024-07-05"),
		)

	def test_hybrid_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-01",
			rate_of_interest=28,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-01", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 8253)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-29", 50000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

		repayment_entry.load_from_db()

		self.assertEqual(len(repayment_entry.get("repayment_details")), 2)

	def test_multiple_advance_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			1200000,
			"Repay Over Number of Periods",
			36,
			repayment_start_date="2024-06-05",
			posting_date="2024-05-03",
			rate_of_interest=29,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-05-03", repayment_start_date="2024-06-05"
		)
		process_daily_loan_demands(posting_date="2024-06-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-06-05", 50287)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-06-18", 50287, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-12-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-12-05", 251435)
		repayment_entry.submit()

		repayment_entry1 = create_repayment_entry(
			loan.name, "2024-12-21", 150287, repayment_type="Pre Payment"
		)
		repayment_entry1.submit()

		repayment_entry2 = create_repayment_entry(
			loan.name, "2024-12-21", 150287, repayment_type="Pre Payment"
		)
		repayment_entry2.submit()

		# Cancel the entry to check if correct schedule becomes active
		repayment_entry1.cancel()
		repayment_entry2.cancel()

	def test_interest_accrual_and_demand_on_freeze_and_unfreeze(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		loan.load_from_db()
		loan.freeze_account = 1
		loan.freeze_date = "2024-11-10"
		loan.save()

		loan.freeze_account = 0
		loan.save()

	def test_loan_write_off_entry(self):
		frappe.db.set_value(
			"Loan Product", "Term Loan Product 4", "write_off_recovery_account", "Write Off Recovery - _TC"
		)
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)

		repayment = create_repayment_entry(
			loan.name, "2024-12-05", 1000000, repayment_type="Write Off Recovery"
		)

		repayment.submit()

	def test_interest_accrual_overlap(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			1500000,
			"Repay Over Number of Periods",
			30,
			repayment_start_date="2025-01-05",
			posting_date="2024-11-28",
			rate_of_interest=28,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-11-28", repayment_start_date="2025-01-05"
		)

		# Process Loan Interest Accrual
		process_loan_interest_accrual_for_loans(posting_date="2024-12-03", loan=loan.name)
		process_loan_interest_accrual_for_loans(posting_date="2024-12-04", loan=loan.name)
		process_loan_interest_accrual_for_loans(posting_date="2024-12-05", loan=loan.name)

		process_daily_loan_demands(posting_date="2024-12-05", loan=loan.name)

		repayment = create_repayment_entry(loan.name, "2024-12-05", 1150, repayment_type="Pre Payment")

		repayment.submit()
		process_loan_interest_accrual_for_loans(posting_date="2024-12-08", loan=loan.name)

		process_daily_loan_demands(posting_date="2025-01-05", loan=loan.name)
		process_loan_interest_accrual_for_loans(posting_date="2025-01-10", loan=loan.name)

		repayment = create_repayment_entry(loan.name, "2025-01-03", 10000, repayment_type="Pre Payment")

		repayment.submit()

	def test_principal_amount_paid(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(
			loan.name, "2024-04-05", 60000, repayment_type="Pre Payment"
		)

		repayment_entry.submit()
		repayment_entry.load_from_db()

		self.assertEqual(repayment_entry.principal_amount_paid, 49754.1)

	def test_additional_interest(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		# Process Loan Interest Accrual
		process_loan_interest_accrual_for_loans(posting_date="2024-05-10", loan=loan.name)

	def test_npa_loan(self):
		loan = create_loan(
			"Customer B",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		process_loan_interest_accrual_for_loans(posting_date="2024-04-10", loan=loan.name)

		create_process_loan_classification(posting_date="2024-10-05", loan=loan.name)

		create_process_loan_classification(posting_date="2024-11-05", loan=loan.name)

		# repayment_entry = create_repayment_entry(loan.name, "2024-10-05", 47523)
		# repayment_entry.submit()

	def test_npa_for_loc(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2024-12-05",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		create_process_loan_classification(posting_date="2024-10-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-10-05", 47523)
		repayment_entry.submit()

	def test_shortfall_loan_close_limit(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			2,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-04-05", 257840)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 257320.97)
		repayment_entry.submit()

	def test_excess_loan_close_limit(self):
		frappe.db.set_value(
			"Loan Product",
			"Term Loan Product 4",
			"customer_refund_account",
			"Customer Refund Account - _TC",
		)
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			2,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-04-05", 257840)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-05", 257950.97, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

	def test_full_settlement(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2000000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-08-05",
			posting_date="2024-07-05",
			rate_of_interest=22,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-07-05", repayment_start_date="2024-08-05"
		)

		process_daily_loan_demands(posting_date="2024-09-05", loan=loan.name)
		repayment_entry = create_repayment_entry(
			loan.name, "2024-08-05", 1000000, repayment_type="Full Settlement"
		)
		repayment_entry.submit()

	def test_backdated_pre_payment(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 2",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-08-16",
			posting_date="2024-08-16",
			rate_of_interest=8.5,
			applicant_type="Customer",
			moratorium_tenure=1,
			moratorium_type="Principal",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-08-16"
		)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-08-25", 15000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-09-01", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-09-01", 138.90, repayment_type="Normal Repayment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-10-01", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-09-26", 15000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

	def test_dpd_calculation(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			30,
			repayment_start_date="2024-10-05",
			posting_date="2024-09-15",
			rate_of_interest=10,
			applicant_type="Customer",
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-09-15", repayment_start_date="2024-10-05"
		)
		process_daily_loan_demands(posting_date="2024-10-05", loan=loan.name)

		for date in ["2024-10-05", "2024-10-06", "2024-10-07", "2024-10-08", "2024-10-09", "2024-10-10"]:
			create_process_loan_classification(posting_date=date, loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-10-05", 3000)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-10-09", 782)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-11-05", 3000)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-11-10", 782)
		repayment_entry.submit()

		frappe.db.sql(
			"""
		update `tabDays Past Due Log` set days_past_due = -1 where loan = %s """,
			loan.name,
		)

		create_process_loan_classification(posting_date="2024-10-05", loan=loan.name)

		dpd_logs = frappe.db.sql(
			"""
			SELECT posting_date, days_past_due
			FROM `tabDays Past Due Log`
			WHERE loan = %s
			ORDER BY posting_date
			""",
			(loan.name),
			as_dict=1,
		)

		expected_dpd_values = {
			"2024-10-05": 1,
			"2024-10-06": 2,
			"2024-10-07": 3,
			"2024-10-08": 4,
			"2024-10-09": 0,  # Fully repaid
			"2024-10-10": 0,
			"2024-11-04": 0,
			"2024-11-05": 1,  # DPD starts again after repayment
			"2024-11-06": 2,
			"2024-11-07": 3,
			"2024-11-08": 4,
			"2024-11-09": 5,
			"2024-11-10": 0,  # Fully repaid
		}

		for log in dpd_logs:
			posting_date = log["posting_date"]
			dpd_value = log["days_past_due"]

			posting_date_str = posting_date.strftime("%Y-%m-%d")

			expected_dpd = expected_dpd_values.get(posting_date_str, 0)
			self.assertEqual(
				dpd_value,
				expected_dpd,
				f"DPD mismatch for {posting_date}: Expected {expected_dpd}, got {dpd_value}",
			)


def create_secured_demand_loan(applicant, disbursement_amount=None):
	frappe.db.set_value(
		"Company",
		"_Test Company",
		"collection_offset_sequence_for_standard_asset",
		"Test Standard Loan Demand Offset Order 1",
	)

	pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

	loan_application = create_loan_application("_Test Company", applicant, "Demand Loan", pledge)
	create_loan_security_assignment(loan_application)

	loan = create_demand_loan(applicant, "Demand Loan", loan_application, posting_date="2019-10-01")
	loan.submit()

	first_date = "2019-10-01"
	last_date = "2019-10-30"

	make_loan_disbursement_entry(
		loan.name, disbursement_amount or loan.loan_amount, disbursement_date=first_date
	)
	process_loan_interest_accrual_for_loans(posting_date=last_date)

	return loan


def create_loan_scenario_for_penalty(doc):
	pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

	loan_application = create_loan_application("_Test Company", doc.applicant2, "Demand Loan", pledge)
	create_loan_security_assignment(loan_application)
	loan = create_demand_loan(
		doc.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
	)
	loan.submit()

	first_date = "2019-10-01"
	last_date = "2019-10-30"

	make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
	process_loan_interest_accrual_for_loans(posting_date=last_date)

	amounts = calculate_amounts(loan.name, add_days(last_date, 1))
	paid_amount = amounts["interest_amount"] / 2

	repayment_entry = create_repayment_entry(loan.name, add_days(last_date, 5), paid_amount)

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
		"Interest Waiver Account",
		"Direct Expenses - _TC",
		"Expense",
		"Expense Account",
		"Profit and Loss",
	)

	create_account(
		"Penalty Waiver Account",
		"Direct Expenses - _TC",
		"Expense",
		"Expense Account",
		"Profit and Loss",
	)

	create_account(
		"Additional Interest Income Account",
		"Direct Income - _TC",
		"Income",
		"Income Account",
		"Profit and Loss",
	)

	create_account(
		"Additional Interest Accrued Account",
		"Loans and Advances (Assets) - _TC",
		"Asset",
		"Receivable",
		"Balance Sheet",
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
		"Additional Interest Receivable",
		"Loans and Advances (Assets) - _TC",
		"Asset",
		"Receivable",
		"Balance Sheet",
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

	create_account(
		"Suspense Penalty Account", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)

	create_account(
		"Interest Accrued Account", "Loans and Advances (Assets) - _TC", "Asset", "", "Balance Sheet"
	)

	create_account(
		"Additional Interest Accrued Account",
		"Loans and Advances (Assets) - _TC",
		"Asset",
		"",
		"Balance Sheet",
	)

	create_account(
		"Suspense Interest Accrued Account",
		"Loans and Advances (Assets) - _TC",
		"Asset",
		"",
		"Balance Sheet",
	)

	create_account(
		"Penalty Accrued Account", "Loans and Advances (Assets) - _TC", "Asset", "", "Balance Sheet"
	)

	create_account(
		"Broken Period Interest", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)

	create_account(
		"Write Off Account", "Direct Expenses - _TC", "Expense", "Expense Account", "Profit and Loss"
	)

	create_account(
		"Write Off Recovery", "Direct Expenses - _TC", "Expense", "Expense Account", "Profit and Loss"
	)

	create_account(
		"Customer Refund Account",
		"Loans and Advances (Assets) - _TC",
		"Asset",
		"",
		"Balance Sheet",
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
	suspense_interest_income="Suspense Income Account - _TC",
	repayment_method=None,
	repayment_periods=None,
	repayment_schedule_type="Monthly as per repayment start date",
	repayment_date_on=None,
	days_past_due_threshold_for_npa=None,
	min_days_bw_disbursement_first_repayment=None,
	interest_accrued_account="Interest Accrued Account - _TC",
	penalty_accrued_account="Penalty Accrued Account - _TC",
	broken_period_interest_recovery_account="Broken Period Interest - _TC",
	cyclic_day_of_the_month=5,
):

	if not frappe.db.exists("Loan Product", product_code):
		loan_product = frappe.get_doc(
			{
				"doctype": "Loan Product",
				"company": "_Test Company",
				"product_code": product_code,
				"product_name": product_name,
				"is_term_loan": is_term_loan,
				"repayment_schedule_type": repayment_schedule_type,
				"cyclic_day_of_the_month": cyclic_day_of_the_month,
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
				"suspense_interest_income": suspense_interest_income,
				"interest_accrued_account": interest_accrued_account,
				"penalty_accrued_account": penalty_accrued_account,
				"broken_period_interest_recovery_account": broken_period_interest_recovery_account,
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
				"loan_security_code": "Test Security 1",
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
				"loan_security_code": "Test Security 2",
				"loan_security_name": "Test Security 2",
				"unit_of_measure": "Nos",
				"haircut": 50.00,
			}
		).insert(ignore_permissions=True)


def make_loan_disbursement_entry(loan, amount, disbursement_date=None, repayment_start_date=None):
	loan_disbursement_entry = frappe.new_doc("Loan Disbursement")
	loan_disbursement_entry.against_loan = loan
	loan_disbursement_entry.disbursement_date = disbursement_date or nowdate()
	loan_disbursement_entry.repayment_start_date = (
		repayment_start_date or disbursement_date or nowdate()
	)
	loan_disbursement_entry.company = "_Test Company"
	loan_disbursement_entry.disbursed_amount = amount
	loan_disbursement_entry.cost_center = "Main - _TC"

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


def create_repayment_entry(loan, posting_date, paid_amount, repayment_type="Normal Repayment"):
	lr = frappe.new_doc("Loan Repayment")
	lr.against_loan = loan
	lr.company = "_Test Company"
	lr.posting_date = posting_date or nowdate()
	lr.amount_paid = paid_amount
	lr.repayment_type = repayment_type
	lr.insert(ignore_permissions=True)

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
	repayment_periods=None,
	applicant_type=None,
	repayment_start_date=None,
	posting_date=None,
	monthly_repayment_amount=None,
	rate_of_interest=None,
	limit_applicable_start=None,
	limit_applicable_end=None,
	loan_partner=None,
	moratorium_tenure=None,
	moratorium_type=None,
):

	loan = frappe.get_doc(
		{
			"doctype": "Loan",
			"applicant_type": applicant_type or "Employee",
			"company": "_Test Company",
			"applicant": applicant,
			"loan_product": loan_product,
			"loan_amount": loan_amount,
			"maximum_limit_amount": loan_amount,
			"repayment_method": repayment_method,
			"repayment_periods": repayment_periods,
			"monthly_repayment_amount": monthly_repayment_amount,
			"repayment_start_date": repayment_start_date or nowdate(),
			"posting_date": posting_date or nowdate(),
			"rate_of_interest": rate_of_interest,
			"limit_applicable_start": limit_applicable_start,
			"limit_applicable_end": limit_applicable_end,
			"loan_partner": loan_partner,
			"moratorium_tenure": moratorium_tenure,
			"moratorium_type": moratorium_type,
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
	loan = frappe.new_doc("Loan")
	loan.company = "_Test Company"
	loan.applicant_type = "Customer"
	loan.applicant = applicant
	loan.loan_product = loan_product
	loan.posting_date = posting_date or nowdate()
	loan.loan_application = loan_application
	loan.is_term_loan = 0
	loan.is_secured_loan = 1
	loan.payment_account = "Payment Account - _TC"
	loan.loan_account = "Loan Account - _TC"
	loan.interest_income_account = "Interest Income Account - _TC"
	loan.penalty_income_account = "Penalty Income Account - _TC"

	loan.save()

	return loan


def set_loan_settings_in_company(company=None):
	if not company:
		company = "_Test Company"
	company = frappe.get_doc("Company", company)
	company.min_days_bw_disbursement_first_repayment = 15
	company.save()


def setup_loan_demand_offset_order(company=None):
	if not company:
		company = "_Test Company"

	create_demand_offset_order("Test Loan Demand Offset Order", ["Penalty", "Interest", "Principal"])
	create_demand_offset_order(
		"Test Standard Loan Demand Offset Order", ["EMI (Principal + Interest)", "Penalty", "Charges"]
	)
	create_demand_offset_order(
		"Test Standard Loan Demand Offset Order 1", ["Penalty", "Interest", "Charges"]
	)

	doc = frappe.get_doc("Company", company)
	if not doc.get("collection_offset_sequence_for_standard_asset"):
		doc.collection_offset_sequence_for_standard_asset = "Test Standard Loan Demand Offset Order"

	if not doc.get("collection_offset_sequence_for_sub_standard_asset"):
		doc.collection_offset_sequence_for_non_standard_asset = "Test Loan Demand Offset Order"

	if not doc.get("collection_offset_sequence_for_written_off_asset"):
		doc.collection_offset_sequence_for_written_off_asset = "Test Loan Demand Offset Order"

	if not doc.get("collection_offset_sequence_for_settlement_collection"):
		doc.collection_offset_sequence_for_settlement_collection = "Test Loan Demand Offset Order"

	doc.save()


def create_demand_offset_order(order_name, components):
	if not frappe.db.get_value("Loan Demand Offset Order", {"title": order_name}):
		order = frappe.new_doc("Loan Demand Offset Order")
		order.title = order_name

		for component in components:
			order.append("components", {"demand_type": component})

		order.insert()


def create_loan_write_off(loan, posting_date, write_off_amount=None):
	loan_write_off = frappe.new_doc("Loan Write Off")
	loan_write_off.loan = loan
	loan_write_off.posting_date = posting_date
	loan_write_off.company = "_Test Company"
	loan_write_off.write_off_account = "Write Off Account - _TC"
	loan_write_off.save()
	loan_write_off.submit()

	return loan_write_off
