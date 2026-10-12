# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, add_to_date, flt, get_datetime, nowdate

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
	get_disbursal_amount,
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
	update_loan_security_price,
)
from lending.tests.utils import LendingTestSuite


class TestLoanSecurityShortfall(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
		create_loan_security_price("Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_security_shortfall(self):
		create_loan_security_price("Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
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

		create_loan_security_price("Test Security 2", 100, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
		create_process_loan_security_shortfall()

		loan_security_shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})

		self.assertTrue(loan_security_shortfall)
		self.assertEqual(flt(loan_security_shortfall.loan_amount, 2), 1000000.00)
		self.assertEqual(flt(loan_security_shortfall.security_value, 2), 800000.00)
		self.assertEqual(flt(loan_security_shortfall.shortfall_amount, 2), 600000.00)

		create_loan_security_price("Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
		create_process_loan_security_shortfall()

		loan_security_shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})
		self.assertEqual(loan_security_shortfall.status, "Completed")
		self.assertEqual(loan_security_shortfall.shortfall_amount, 0)

	def test_lowering_ltv_warns_about_running_loans(self):
		pledges = [{"loan_security": "Test Security 2", "qty": 8000.00, "haircut": 50}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)
		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()
		make_loan_disbursement_entry(loan.name, loan.loan_amount)

		security = frappe.get_doc("Loan Security", "Test Security 2")
		self.addCleanup(frappe.db.set_value, "Loan Security", security.name, "loan_to_value_ratio", 50)

		frappe.clear_messages()
		security.loan_to_value_ratio = 40
		security.save()

		messages = [message.get("message") for message in frappe.get_message_log()]
		self.assertTrue(any(loan.name in message for message in messages))

		frappe.clear_messages()
		security.loan_to_value_ratio = 60
		security.save()

		messages = [message.get("message") for message in frappe.get_message_log()]
		self.assertFalse(any(loan.name in message for message in messages))

	def test_lowering_ltv_warns_about_customer_level_pledges(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		customer = frappe.get_doc(get_customer_dict("LTV Warning Customer")).insert().name
		create_loan_security_assignment(
			applicant=customer,
			applicant_type="Customer",
			securities=[{"loan_security": "Test Security 1", "qty": 4000.00}],
			company="_Test Company",
		)

		loan = create_loan(
			customer,
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
			loan.name, 500000, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		security = frappe.get_doc("Loan Security", "Test Security 1")
		self.addCleanup(frappe.db.set_value, "Loan Security", security.name, "loan_to_value_ratio", 50)

		# ₹20,00,000 of shares: LTV 30 allows ₹6,00,000, LTV 20 allows ₹4,00,000 against ₹5,00,000 drawn
		frappe.clear_messages()
		security.loan_to_value_ratio = 30
		security.save()

		messages = [message.get("message") for message in frappe.get_message_log()]
		self.assertFalse(any(customer in message for message in messages))

		frappe.clear_messages()
		security.loan_to_value_ratio = 20
		security.save()

		messages = [message.get("message") for message in frappe.get_message_log()]
		self.assertTrue(any(customer in message for message in messages))

	def set_security_ltvs(self, ltv_by_security):
		# The type "Stock" stays at 50, so neither the type's LTV nor the first security's gives these results
		self.assertEqual(flt(frappe.db.get_value("Loan Security Type", "Stock", "loan_to_value_ratio")), 50)

		for security, ltv in ltv_by_security.items():
			self.addCleanup(frappe.db.set_value, "Loan Security", security, "loan_to_value_ratio", 50)
			frappe.db.set_value("Loan Security", security, "loan_to_value_ratio", ltv)

	def test_shortfall_and_release_use_each_security_ltv(self):
		from lending.loan_management.doctype.loan.loan import unpledge_security

		# ₹5,00,000 of each security, lent at haircut 50
		pledges = [
			{"loan_security": "Test Security 1", "qty": 1000.00, "haircut": 50},
			{"loan_security": "Test Security 2", "qty": 2000.00, "haircut": 50},
		]
		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)
		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()
		self.assertEqual(loan.loan_amount, 500000)
		make_loan_disbursement_entry(loan.name, loan.loan_amount)

		# LTV 80 and 40 allow ₹4,00,000 + ₹2,00,000 = ₹6,00,000. Each unit of security 2 released frees ₹100
		self.set_security_ltvs({"Test Security 1": 80, "Test Security 2": 40})

		with self.assertRaises(frappe.ValidationError):
			unpledge_security(loan=loan.name, security_map={"Test Security 2": 1100}, save=1)

		unpledge_security(loan=loan.name, security_map={"Test Security 2": 900}, save=1)

		# LTV 60 and 30 allow ₹3,00,000 + ₹1,50,000 = ₹4,50,000 against ₹5,00,000 drawn
		self.set_security_ltvs({"Test Security 1": 60, "Test Security 2": 30})
		create_process_loan_security_shortfall()

		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name, "status": "Pending"})
		self.assertEqual(flt(shortfall.security_value, 2), 1000000.00)
		self.assertEqual(flt(shortfall.shortfall_amount, 2), 50000.00)

	def test_sanctioned_limit_uses_each_security_ltv(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		from lending.loan_management.doctype.loan_security_release.loan_security_release import (
			update_sanctioned_loan_amount_for_applicant,
		)

		customer = frappe.get_doc(get_customer_dict("Unequal LTV Customer")).insert().name
		create_loan_security_assignment(
			applicant=customer,
			applicant_type="Customer",
			securities=[
				{"loan_security": "Test Security 1", "qty": 1000.00},
				{"loan_security": "Test Security 2", "qty": 2000.00},
			],
			company="_Test Company",
		)

		# LTV 80 and 40 on ₹5,00,000 each allow ₹4,00,000 + ₹2,00,000
		self.set_security_ltvs({"Test Security 1": 80, "Test Security 2": 40})

		update_sanctioned_loan_amount_for_applicant(customer, "Customer")
		sanctioned_limit = frappe.db.get_value(
			"Sanctioned Loan Amount", {"applicant": customer}, "sanctioned_amount_limit"
		)
		self.assertEqual(flt(sanctioned_limit), 600000)

		frappe.db.set_value("Sanctioned Loan Amount", {"applicant": customer}, "sanctioned_amount_limit", 0)
		create_process_loan_security_shortfall()
		sanctioned_limit = frappe.db.get_value(
			"Sanctioned Loan Amount", {"applicant": customer}, "sanctioned_amount_limit"
		)
		self.assertEqual(flt(sanctioned_limit), 600000)

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

	def test_security_shortfall_at_customer_level_security_pledging(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		pledge = [
			{
				"loan_security": "Test Security 1",
				"qty": 4000.00,
			}
		]

		customer = frappe.get_doc(get_customer_dict("Sanctioned Amount Customer")).insert().name

		create_loan_security_assignment(applicant=customer, applicant_type="Customer", securities=pledge, company="_Test Company")

		loan = create_loan(
			customer,
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
			loan.name, 500000, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		update_loan_security_price("Test Security 1", 200, "INR", get_datetime(), get_datetime(add_to_date(nowdate(), hours=24)))

		create_process_loan_security_shortfall()

		# Check if shortfall entry is created against the applicant
		shortfall_details = frappe.db.get_value("Loan Security Shortfall", {
			"applicant": customer,
			"status": "Pending"
		}, ["name", "shortfall_amount"], as_dict=1)

		self.assertTrue(shortfall_details)
		self.assertEqual(flt(shortfall_details.shortfall_amount), 100000)

		# Test Customer Sanctioned Limit
		sanctioned_limit = frappe.db.get_value("Sanctioned Loan Amount", {"applicant": customer}, "sanctioned_amount_limit")
		self.assertEqual(flt(sanctioned_limit), 400000)
