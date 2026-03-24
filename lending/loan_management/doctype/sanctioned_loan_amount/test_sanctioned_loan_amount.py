# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe
from frappe.utils import add_days, nowdate

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.tests.test_utils import (
	create_loan,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_release,
	create_loan_security_type,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)


class TestSanctionedLoanAmount(unittest.TestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
		create_loan_security_price("Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)

	def test_sanctioned_loan_amount_limit_for_secured_loan(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		pledge = [
			{
				"loan_security": "Test Security 1",
				"qty": 4000.00,
			}
		]

		customer = frappe.get_doc(get_customer_dict("Sanctioned Amount Customer")).insert().name
		create_loan_security_assignment(applicant=customer, applicant_type="Customer", securities=pledge, company="_Test Company")

		sanctioned_amount_limit = frappe.db.get_value("Sanctioned Loan Amount", {"applicant": customer, "applicant_type": "Customer"}, "sanctioned_amount_limit")
		self.assertEqual(sanctioned_amount_limit, 1000000)

		loan = create_loan(
			customer,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, 1000000, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		self.assertRaises(frappe.ValidationError, create_loan,
			customer,
			"Term Loan Product 4",
			1500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer"
		)

		pledge = [
			{
				"loan_security": "Test Security 2",
				"qty": 16000.00,
			}
		]

		create_loan_security_assignment(applicant=customer, applicant_type="Customer", securities=pledge, company="_Test Company")
		sanctioned_amount_limit = frappe.db.get_value("Sanctioned Loan Amount", {"applicant": customer, "applicant_type": "Customer"}, "sanctioned_amount_limit")
		self.assertEqual(sanctioned_amount_limit, 3000000)

		loan = create_loan(
			customer,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, 1000000, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		self.assertRaises(frappe.ValidationError, create_loan,
			customer,
			"Term Loan Product 4",
			1500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer"
		)

		create_loan_security_release(
			applicant=customer,
			applicant_type="Customer",
			securities=pledge
		)

		sanctioned_amount_limit = frappe.db.get_value("Sanctioned Loan Amount", {"applicant": customer, "applicant_type": "Customer"}, "sanctioned_amount_limit")
		self.assertEqual(sanctioned_amount_limit, 1000000)
