# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.setup.doctype.employee.test_employee import make_employee

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan,
	get_instalment_count,
)
from lending.tests.test_utils import (
	create_loan_accounts,
	create_loan_product,
	make_loan_disbursement_entry,
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

	def test_instalment_count_for_repayment_frequency(self):
		for months, frequency, expected in (
			(12, "Monthly", 12),
			(12, "Bi-Weekly", 26),
			(12, "Weekly", 52),
			(12, "Quarterly", 4),
			(18, "Bi-Weekly", 39),
			(10, "Bi-Weekly", 22),
		):
			self.assertEqual(get_instalment_count(months, frequency), expected, f"{months} {frequency}")

	def test_tenure_in_months_becomes_instalments_for_bi_weekly_loan(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.repayment_periods = 12
		loan_application.repayment_frequency = "Bi-Weekly"
		loan_application.status = "Approved"
		loan_application.save()
		loan_application.submit()

		self.assertLess(loan_application.repayment_amount, 14923)

		loan = create_loan(loan_application.name)
		self.assertEqual(loan.repayment_frequency, "Bi-Weekly")
		self.assertEqual(loan.repayment_periods, 26)
		loan.repayment_start_date = "2026-01-15"
		loan.posting_date = "2026-01-01"
		loan.save()
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-01-01", repayment_start_date="2026-01-15"
		)

		schedule = frappe.get_doc("Loan Repayment Schedule", {"loan": loan.name, "status": "Active"})
		self.assertEqual(len(schedule.repayment_schedule), 26)
		self.assertEqual(schedule.repayment_schedule[-1].payment_date.isoformat(), "2026-12-31")

	def test_monthly_loan_keeps_tenure_in_months(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.status = "Approved"
		loan_application.save()
		loan_application.submit()

		loan = create_loan(loan_application.name)
		self.assertEqual(loan.repayment_periods, 18)

	def test_fixed_amount_method_resets_repayment_frequency(self):
		loan_application = frappe.get_doc("Loan Application", {"applicant": self.applicant})
		loan_application.repayment_frequency = "Bi-Weekly"
		loan_application.repayment_method = "Repay Fixed Amount per Period"
		loan_application.repayment_amount = 15000
		loan_application.save()

		self.assertEqual(loan_application.repayment_frequency, "Monthly")
