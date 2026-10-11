# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from lending.tests.utils import LendingTestSuite


def make_loan_security_type(**values):
	doc = frappe.new_doc("Loan Security Type")
	doc.update({"loan_security_type": "_Test LTV Type", **values})
	return doc.insert()


class TestLoanSecurityType(LendingTestSuite):
	def test_ltv_follows_haircut(self):
		doc = make_loan_security_type(haircut=40)

		self.assertEqual(doc.loan_to_value_ratio, 60)

	def test_typed_ltv_is_replaced(self):
		doc = make_loan_security_type(haircut=50, loan_to_value_ratio=70)

		self.assertEqual(doc.loan_to_value_ratio, 50)

	def test_zero_haircut_lends_full_value(self):
		doc = make_loan_security_type(haircut=0)

		self.assertEqual(doc.loan_to_value_ratio, 100)

	def test_changing_haircut_needs_no_other_edit(self):
		doc = make_loan_security_type(haircut=40)
		doc.haircut = 30
		doc.save()

		self.assertEqual(doc.loan_to_value_ratio, 70)

	def test_haircut_out_of_range(self):
		self.assertRaises(frappe.ValidationError, make_loan_security_type, haircut=120)
		self.assertRaises(frappe.ValidationError, make_loan_security_type, haircut=-10)
