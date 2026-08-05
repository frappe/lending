# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.setup.doctype.employee.test_employee import make_employee

from lending.tests.test_utils import (
	create_loan_accounts,
	create_loan_product,
	set_loan_settings_in_company,
)
from lending.tests.utils import LendingTestSuite


class TestLoanApplication(LendingTestSuite):
	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		create_loan_product(
			"Home Loan",
			"Home Loan",
			500000,
			9.2,
			0,
			1,
			0,
			repayment_schedule_type="Monthly as per repayment start date",
		)
		self.applicant = make_employee("kate_loan@loan.com", "_Test Company")
		self.create_loan_application()

	def create_loan_application(self):
		loan_application = frappe.new_doc("Loan Application")
		loan_application.update(
			{
				"applicant": self.applicant,
				"loan_product": "Home Loan",
				"rate_of_interest": 9.2,
				"loan_amount": 250000,
				"repayment_method": "Repay Over Number of Periods",
				"repayment_periods": 18,
				"company": "_Test Company",
				"applicant_type": "Employee",
				"applicant_email_address": "lending@example.com",
				"applicant_phone_number": "+91-9102837465",
			}
		)
		loan_application.insert()

	def test_loan_totals(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})

		self.assertEqual(loan_application.total_payable_interest, 18599)
		self.assertEqual(loan_application.total_payable_amount, 268599)
		self.assertEqual(loan_application.repayment_amount, 14923)

		loan_application.repayment_periods = 24
		loan_application.save()
		loan_application.reload()

		self.assertEqual(loan_application.total_payable_interest, 24657)
		self.assertEqual(loan_application.total_payable_amount, 274657)
		self.assertEqual(loan_application.repayment_amount, 11445)

	def test_dti_foir_computed_on_validate(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.monthly_income = 100000
		loan_application.existing_obligations = 10000
		loan_application.save()
		loan_application.reload()

		self.assertEqual(loan_application.proposed_emi, 14923)
		self.assertEqual(loan_application.dti_ratio, 10.0)
		self.assertEqual(loan_application.foir_ratio, 24.92)

	def test_dti_foir_zero_when_no_income(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.monthly_income = 0
		loan_application.existing_obligations = 5000
		loan_application.save()
		loan_application.reload()

		self.assertEqual(loan_application.dti_ratio, 0)
		self.assertEqual(loan_application.foir_ratio, 0)

	def test_eligibility_amount_respects_max_foir(self):
		frappe.db.set_value("Loan Product", "Home Loan", "max_foir", 40)
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.monthly_income = 100000
		loan_application.existing_obligations = 0
		loan_application.save()
		loan_application.reload()

		self.assertTrue(loan_application.eligibility_amount > 0)

		max_emi = 100000 * 40 / 100
		monthly_rate = 9.2 / (12 * 100)
		n = loan_application.repayment_periods
		expected_principal = round(
			max_emi * ((1 + monthly_rate) ** n - 1) / (monthly_rate * (1 + monthly_rate) ** n), 2
		)
		self.assertEqual(loan_application.eligibility_amount, expected_principal)

	def test_eligibility_amount_zero_when_no_income(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.monthly_income = 0
		loan_application.save()
		loan_application.reload()

		self.assertEqual(loan_application.eligibility_amount, 0)

	def test_ltv_ratio_for_secured_loan(self):
		from lending.tests.test_utils import create_loan_security, create_loan_security_type

		create_loan_security_type()
		create_loan_security()

		loan_application = frappe.new_doc("Loan Application")
		loan_application.update(
			{
				"applicant": self.applicant,
				"loan_product": "Home Loan",
				"rate_of_interest": 9.2,
				"repayment_method": "Repay Over Number of Periods",
				"repayment_periods": 18,
				"company": "_Test Company",
				"applicant_type": "Employee",
				"applicant_email_address": "lending@example.com",
				"applicant_phone_number": "+91-9102837465",
				"is_secured_loan": 1,
			}
		)
		loan_application.append(
			"proposed_pledges",
			{"loan_security": "Test Security 1", "qty": 4000, "loan_security_price": 100, "haircut": 50},
		)
		loan_application.insert()

		self.assertEqual(loan_application.maximum_loan_amount, 200000)
		self.assertEqual(loan_application.loan_amount, 200000)
		self.assertEqual(loan_application.ltv_ratio, 100.0)

	def test_ltv_ratio_zero_for_unsecured_loan(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.save()
		loan_application.reload()

		self.assertEqual(loan_application.is_secured_loan, 0)
		self.assertEqual(loan_application.ltv_ratio, 0)

	def test_ltv_ratio_partial_for_multiple_pledges(self):
		from lending.tests.test_utils import create_loan_security, create_loan_security_type

		create_loan_security_type()
		create_loan_security()

		loan_application = frappe.new_doc("Loan Application")
		loan_application.update(
			{
				"applicant": self.applicant,
				"loan_product": "Home Loan",
				"rate_of_interest": 9.2,
				"repayment_method": "Repay Over Number of Periods",
				"repayment_periods": 18,
				"company": "_Test Company",
				"applicant_type": "Employee",
				"applicant_email_address": "lending@example.com",
				"applicant_phone_number": "+91-9102837465",
				"is_secured_loan": 1,
				"loan_amount": 100000,
			}
		)
		loan_application.append(
			"proposed_pledges",
			{"loan_security": "Test Security 1", "qty": 2000, "loan_security_price": 100, "haircut": 50},
		)
		loan_application.append(
			"proposed_pledges",
			{"loan_security": "Test Security 2", "qty": 2000, "loan_security_price": 100, "haircut": 50},
		)
		loan_application.insert()

		self.assertEqual(loan_application.maximum_loan_amount, 200000)
		self.assertEqual(loan_application.ltv_ratio, 50.0)

	def test_proposed_emi_zero_for_non_term_loan(self):
		from lending.tests.test_utils import create_loan_product

		create_loan_product(
			"Utils Demand Loan",
			"Utils Demand Loan",
			500000,
			9.2,
			0,
			0,
		)

		loan_application = frappe.new_doc("Loan Application")
		loan_application.update(
			{
				"applicant": self.applicant,
				"loan_product": "Utils Demand Loan",
				"rate_of_interest": 9.2,
				"loan_amount": 250000,
				"company": "_Test Company",
				"applicant_type": "Employee",
				"applicant_email_address": "lending@example.com",
				"applicant_phone_number": "+91-9102837465",
			}
		)
		loan_application.insert()

		self.assertEqual(loan_application.is_term_loan, 0)
		self.assertEqual(loan_application.proposed_emi, 0)

	def test_dti_zero_but_foir_positive_when_no_existing_obligations(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.monthly_income = 100000
		loan_application.existing_obligations = 0
		loan_application.save()
		loan_application.reload()

		self.assertEqual(loan_application.dti_ratio, 0)
		self.assertTrue(loan_application.foir_ratio > 0)

	def test_eligibility_amount_zero_when_obligations_exceed_foir_cap(self):
		frappe.db.set_value("Loan Product", "Home Loan", "max_foir", 30)
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.monthly_income = 50000
		loan_application.existing_obligations = 30000
		loan_application.save()
		loan_application.reload()

		self.assertEqual(loan_application.eligibility_amount, 0)
