# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from lending.tests.utils import LendingTestSuite


def make_loan_security_type(**values):
	doc = frappe.new_doc("Loan Security Type")
	doc.update({"loan_security_type": "_Test LTV Type", **values})
	return doc.insert()


class TestLoanSecurityType(LendingTestSuite):
	def test_ltv_is_derived_from_haircut(self):
		doc = make_loan_security_type(haircut=40)

		self.assertEqual(doc.loan_to_value_ratio, 60)

	def test_haircut_is_derived_from_ltv(self):
		doc = make_loan_security_type(loan_to_value_ratio=75)

		self.assertEqual(doc.haircut, 25)

	def test_haircut_and_ltv_must_add_up_to_100(self):
		self.assertRaises(
			frappe.ValidationError, make_loan_security_type, haircut=50, loan_to_value_ratio=60
		)

	def test_zero_haircut_and_zero_ltv_are_rejected(self):
		# Drawing power would count the full value while the shortfall check counts none.
		self.assertRaises(
			frappe.ValidationError, make_loan_security_type, haircut=0, loan_to_value_ratio=0
		)

	def test_zero_haircut_with_full_ltv_is_allowed(self):
		doc = make_loan_security_type(haircut=0, loan_to_value_ratio=100)

		self.assertEqual((doc.haircut, doc.loan_to_value_ratio), (0, 100))

	def test_matching_haircut_and_ltv_are_kept(self):
		doc = make_loan_security_type(haircut=50, loan_to_value_ratio=50)

		self.assertEqual((doc.haircut, doc.loan_to_value_ratio), (50, 50))

	def test_percent_out_of_range(self):
		self.assertRaises(frappe.ValidationError, make_loan_security_type, haircut=120)
		self.assertRaises(frappe.ValidationError, make_loan_security_type, loan_to_value_ratio=-10)
