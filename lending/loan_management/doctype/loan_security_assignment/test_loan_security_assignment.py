# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe
from frappe.utils import add_to_date, get_datetime, nowdate

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.tests.test_utils import (
	create_loan,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)


class TestLoanSecurityAssignment(unittest.TestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price(
			"Test Security 1", 500, "Nos", get_datetime(), get_datetime(add_to_date(nowdate(), hours=24))
		)
		create_loan_security_price(
			"Test Security 2", 250, "Nos", get_datetime(), get_datetime(add_to_date(nowdate(), hours=24))
		)

	def test_loan_security_validations(self):
		pledge = [
			{
				"loan_security": "Test Security 1",
				"qty": 4000.00,
			}
		]

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			1500000,
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

		lsa = create_loan_security_assignment(loan=loan.name, securities=pledge)

		lsa_doc = frappe.get_doc("Loan Security Assignment", lsa)

		self.assertEqual(lsa_doc.total_security_value, 2000000)
		self.assertEqual(lsa_doc.maximum_loan_value, 1000000)

		self.assertRaises(frappe.exceptions.ValidationError, make_loan_disbursement_entry,
			loan.name, 1200000, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		disbursement = make_loan_disbursement_entry(
			loan.name, 900000, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		self.assertTrue(disbursement)
