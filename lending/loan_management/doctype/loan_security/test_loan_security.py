# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from lending.loan_management.doctype.loan_security_type.test_loan_security_type import (
	make_loan_security_type,
)
from lending.tests.utils import LendingTestSuite


def make_loan_security(**values):
	doc = frappe.new_doc("Loan Security")
	doc.update(
		{
			"loan_security_code": "_Test LTV Security",
			"loan_security_name": "_Test LTV Security",
			"loan_security_type": "_Test LTV Type",
			**values,
		}
	)
	return doc.insert()


class TestLoanSecurity(LendingTestSuite):
	def setUp(self):
		super().setUp()
		make_loan_security_type(haircut=40)

	def test_inherits_type_haircut_and_ltv(self):
		doc = make_loan_security()

		self.assertEqual((doc.haircut, doc.loan_to_value_ratio), (40, 60))

	def test_ltv_override_must_match_type_haircut(self):
		# The haircut is always fetched from the type, so an LTV override
		# that disagrees with it would split drawing power and shortfall.
		self.assertRaises(frappe.ValidationError, make_loan_security, loan_to_value_ratio=70)

	def test_ltv_override_does_not_rewrite_zero_haircut(self):
		# Pledges copy the security's haircut and the shortfall check reads the type's LTV,
		# so turning a fetched haircut of 0 into 30 would split the two.
		make_loan_security_type(
			loan_security_type="_Test Zero Haircut Type", haircut=0, loan_to_value_ratio=100
		)

		self.assertRaises(
			frappe.ValidationError,
			make_loan_security,
			loan_security_type="_Test Zero Haircut Type",
			loan_to_value_ratio=70,
		)

	def test_zero_haircut_type_is_inherited(self):
		make_loan_security_type(
			loan_security_type="_Test Zero Haircut Type", haircut=0, loan_to_value_ratio=100
		)

		doc = make_loan_security(loan_security_type="_Test Zero Haircut Type")

		self.assertEqual((doc.haircut, doc.loan_to_value_ratio), (0, 100))
