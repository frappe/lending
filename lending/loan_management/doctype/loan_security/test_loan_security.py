# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	get_ltv_ratio,
)
from lending.loan_management.doctype.loan_security_type.test_loan_security_type import (
	make_loan_security_type,
)
from lending.patches.v16_0.derive_loan_security_ltv_from_haircut import execute as derive_ltv_patch
from lending.tests.utils import LendingTestSuite


def make_loan_security(code="_Test Infosys", **values):
	doc = frappe.new_doc("Loan Security")
	doc.update(
		{
			"loan_security_code": code,
			"loan_security_name": code,
			"loan_security_type": "_Test LTV Type",
			**values,
		}
	)
	return doc.insert()


class TestLoanSecurity(LendingTestSuite):
	def setUp(self):
		super().setUp()
		self.equity = make_loan_security_type(haircut=50)

	def test_follows_type(self):
		doc = make_loan_security(haircut=70)

		self.assertEqual((doc.override_haircut, doc.haircut, doc.loan_to_value_ratio), (0, 50, 50))

	def test_override_sticks(self):
		doc = make_loan_security(override_haircut=1, haircut=70)
		doc.save()

		self.assertEqual((doc.haircut, doc.loan_to_value_ratio), (70, 30))

	def test_override_to_zero_haircut_sticks(self):
		doc = make_loan_security(override_haircut=1, haircut=0)

		self.assertEqual((doc.haircut, doc.loan_to_value_ratio), (0, 100))

	def test_unticking_override_returns_to_type(self):
		doc = make_loan_security(override_haircut=1, haircut=70)
		doc.override_haircut = 0
		doc.save()

		self.assertEqual((doc.haircut, doc.loan_to_value_ratio), (50, 50))

	def test_type_change_reaches_only_securities_that_follow_it(self):
		infosys = make_loan_security()
		suzlon = make_loan_security("_Test Suzlon", override_haircut=1, haircut=70)

		self.equity.haircut = 40
		self.equity.save()

		infosys.reload()
		suzlon.reload()
		self.assertEqual((infosys.haircut, infosys.loan_to_value_ratio), (40, 60))
		self.assertEqual((suzlon.haircut, suzlon.loan_to_value_ratio), (70, 30))

		# Saving the security again after the type changed must not throw.
		infosys.loan_security_name = "Infosys Ltd"
		infosys.save()

	def test_moving_to_another_type_follows_it(self):
		make_loan_security_type(loan_security_type="_Test Gold Type", haircut=25)
		doc = make_loan_security()
		doc.loan_security_type = "_Test Gold Type"
		doc.save()

		self.assertEqual((doc.haircut, doc.loan_to_value_ratio), (25, 75))

	def test_shortfall_reads_the_security_ltv(self):
		make_loan_security("_Test Suzlon", override_haircut=1, haircut=70)

		self.assertEqual(get_ltv_ratio("_Test Suzlon"), 30)

	def test_warns_when_override_lends_more_than_type(self):
		frappe.clear_messages()
		make_loan_security("_Test Suzlon", override_haircut=1, haircut=30)

		self.assertIn("more than its type", str(frappe.message_log))

	def test_no_warning_when_override_lends_less(self):
		frappe.clear_messages()
		make_loan_security("_Test Suzlon", override_haircut=1, haircut=70)

		self.assertNotIn("more than its type", str(frappe.message_log))

	def test_overriding_clears_ltv_before_upgrade(self):
		doc = make_loan_security()
		frappe.db.set_value("Loan Security", doc.name, "ltv_before_upgrade", 70)
		doc.reload()

		doc.override_haircut = 1
		doc.haircut = 30
		doc.save()

		self.assertFalse(doc.ltv_before_upgrade)

	def test_patch_changes_no_security_limit(self):
		follows = make_loan_security()
		stricter = make_loan_security("_Test Suzlon")
		looser = make_loan_security("_Test TCS")
		blank_haircut = make_loan_security_type(loan_security_type="_Test Blank Haircut Type", haircut=0)

		# Shapes develop allowed: a type whose haircut was never entered, and securities whose
		# LTV was typed below and above the type's.
		frappe.db.set_value("Loan Security Type", blank_haircut.name, "loan_to_value_ratio", 70)
		frappe.db.set_value("Loan Security", stricter.name, "loan_to_value_ratio", 30)
		frappe.db.set_value("Loan Security", looser.name, "loan_to_value_ratio", 70)

		derive_ltv_patch()

		self.assertEqual(
			frappe.db.get_value("Loan Security Type", blank_haircut.name, ["haircut", "loan_to_value_ratio"]),
			(30, 70),
		)
		fields = ["override_haircut", "haircut", "loan_to_value_ratio", "ltv_before_upgrade"]
		self.assertEqual(frappe.db.get_value("Loan Security", follows.name, fields), (0, 50, 50, 0))
		self.assertEqual(frappe.db.get_value("Loan Security", stricter.name, fields), (0, 50, 50, 30))
		self.assertEqual(frappe.db.get_value("Loan Security", looser.name, fields), (0, 50, 50, 70))
