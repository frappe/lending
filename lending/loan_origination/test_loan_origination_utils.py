# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

from lending.loan_origination.loan_origination_utils import (
	compute_dti_foir,
	compute_eligibility_amount,
	compute_emi_preview,
	compute_ltv,
	get_max_foir,
)
from lending.tests.test_utils import create_loan_product, set_loan_settings_in_company
from lending.tests.utils import LendingTestSuite


class TestLoanOriginationUtils(LendingTestSuite):
	def setUp(self):
		set_loan_settings_in_company()
		create_loan_product(
			"Utils Home Loan",
			"Utils Home Loan",
			500000,
			9.2,
			0,
			1,
			0,
			repayment_schedule_type="Monthly as per repayment start date",
		)

	def test_compute_emi_preview_missing_inputs_returns_zero(self):
		self.assertEqual(compute_emi_preview(None, 250000, 9.2, 18), 0)
		self.assertEqual(compute_emi_preview("Utils Home Loan", 0, 9.2, 18), 0)
		self.assertEqual(compute_emi_preview("Utils Home Loan", 250000, 0, 18), 0)
		self.assertEqual(compute_emi_preview("Utils Home Loan", 250000, 9.2, 0), 0)

	def test_compute_emi_preview_matches_known_schedule(self):
		emi = compute_emi_preview("Utils Home Loan", 250000, 9.2, 18)
		self.assertEqual(emi, 14923)

	def test_compute_dti_foir_zero_income(self):
		dti, foir = compute_dti_foir(0, 5000, 1000)
		self.assertEqual(dti, 0)
		self.assertEqual(foir, 0)

	def test_compute_dti_foir_zero_obligations(self):
		dti, foir = compute_dti_foir(100000, 0, 14923)
		self.assertEqual(dti, 0)
		self.assertEqual(foir, 14.92)

	def test_compute_dti_foir_normal(self):
		dti, foir = compute_dti_foir(100000, 10000, 14923)
		self.assertEqual(dti, 10.0)
		self.assertEqual(foir, 24.92)

	def test_compute_ltv_no_loan_amount(self):
		self.assertEqual(compute_ltv(0, [frappe._dict(post_haircut_amount=100000)]), 0)

	def test_compute_ltv_no_pledges(self):
		self.assertEqual(compute_ltv(250000, []), 0)

	def test_compute_ltv_zero_post_haircut_value(self):
		pledges = [frappe._dict(post_haircut_amount=0)]
		self.assertEqual(compute_ltv(250000, pledges), 0)

	def test_compute_ltv_partial_ratio(self):
		pledges = [frappe._dict(post_haircut_amount=100000)]
		self.assertEqual(compute_ltv(50000, pledges), 50.0)

	def test_compute_ltv_multiple_pledges_summed(self):
		pledges = [
			frappe._dict(post_haircut_amount=50000),
			frappe._dict(post_haircut_amount=50000),
		]
		self.assertEqual(compute_ltv(50000, pledges), 50.0)

	def test_get_max_foir_falls_back_to_default(self):
		frappe.db.set_value("Loan Product", "Utils Home Loan", "max_foir", 0)
		self.assertEqual(get_max_foir("Utils Home Loan"), 50.0)

	def test_get_max_foir_uses_configured_value(self):
		frappe.db.set_value("Loan Product", "Utils Home Loan", "max_foir", 35)
		self.assertEqual(get_max_foir("Utils Home Loan"), 35.0)

	def test_compute_eligibility_amount_missing_inputs_returns_zero(self):
		self.assertEqual(compute_eligibility_amount(0, 0, 9.2, 18, "Utils Home Loan"), 0)
		self.assertEqual(compute_eligibility_amount(100000, 0, 9.2, 0, "Utils Home Loan"), 0)

	def test_compute_eligibility_amount_obligations_exceed_foir_cap(self):
		frappe.db.set_value("Loan Product", "Utils Home Loan", "max_foir", 40)
		eligibility = compute_eligibility_amount(100000, 40000, 9.2, 18, "Utils Home Loan")
		self.assertEqual(eligibility, 0)

	def test_compute_eligibility_amount_zero_interest_uses_simple_division(self):
		frappe.db.set_value("Loan Product", "Utils Home Loan", "max_foir", 50)
		eligibility = compute_eligibility_amount(100000, 0, 0.0, 18, "Utils Home Loan")
		self.assertEqual(eligibility, 900000)

	def test_compute_eligibility_amount_positive_with_amortization(self):
		frappe.db.set_value("Loan Product", "Utils Home Loan", "max_foir", 50)
		eligibility = compute_eligibility_amount(100000, 0, 9.2, 18, "Utils Home Loan")
		self.assertTrue(eligibility > 0)
