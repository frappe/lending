# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors


import frappe
from frappe.utils import nowdate

from lending.loan_origination.decisioning import (
	build_variable_context,
	evaluate_strategy,
	run_strategy,
)
from lending.loan_origination.doctype.decision_strategy.test_decision_strategy import (
	make_strategy,
	rule,
)
from lending.tests.utils import LendingTestSuite

TEST_LOAN_PRODUCT = "Personal Loan"
OTHER_LOAN_PRODUCT = "Term Loan Product 1"
TEST_CUSTOMER = "_Test Loan Customer"
TEST_PAN = "ABCDE1234F"


def make_lead(income=60000, employment_type="Salaried", date_of_birth="1992-01-01", **overrides):
	values = {
		"doctype": "Loan Lead",
		"applicant_type": "Individual",
		"applicant_name": "Decisioning Test Applicant",
		"email": "decisioning-test@example.com",
		"mobile_number": "+911234500099",
		"date_of_birth": date_of_birth,
		"employment_type": employment_type,
		"income": income,
		"loan_product": TEST_LOAN_PRODUCT,
		"loan_amount": 500000,
		"proposed_tenure": 36,
	}
	values.update(overrides)

	return frappe.get_doc(values).insert(ignore_permissions=True)


def make_application(loan_lead=None, **overrides):
	values = {
		"doctype": "Loan Application",
		"applicant_type": "Customer",
		"applicant": TEST_CUSTOMER,
		"loan_product": TEST_LOAN_PRODUCT,
		"loan_amount": 500000,
		"rate_of_interest": 13.5,
		"is_term_loan": 1,
		"repayment_method": "Repay Over Number of Periods",
		"repayment_periods": 36,
		"posting_date": nowdate(),
		"loan_lead": loan_lead,
	}
	values.update(overrides)

	values.setdefault(
		"company", frappe.db.get_value("Loan Product", values["loan_product"], "company")
	)

	return frappe.get_doc(values).insert(ignore_permissions=True)


def make_bureau_report(score=712, total_emi=8000, applicant=TEST_CUSTOMER, pan=None):
	report = frappe.get_doc(
		{
			"doctype": "Credit Bureau Report",
			"applicant_type": "Customer",
			"applicant": applicant,
			"pan": pan,
			"bureau": "Manual",
			"score": score,
			"total_emi": total_emi,
			"report_date": nowdate(),
		}
	).insert(ignore_permissions=True)
	report.submit()

	return report




















def comments_on(lead):
	return frappe.get_all(
		"Comment",
		filters={"reference_doctype": "Loan Lead", "reference_name": lead.name},
		pluck="content",
	)


class TestAStageThatRanNothingSaysSo(LendingTestSuite):
	def test_no_strategy_is_recorded_on_the_lead(self):
		lead = make_lead()

		self.assertIsNone(run_strategy(lead, "Underwriting-does-not-exist"))
		self.assertTrue(any("no rule was checked" in comment for comment in comments_on(lead)))

	def test_the_loan_product_it_looked_for_is_named(self):
		lead = make_lead()

		run_strategy(lead, "Underwriting-does-not-exist")

		self.assertTrue(any(TEST_LOAN_PRODUCT in comment for comment in comments_on(lead)))

class TestRecommendedTermsTightenRatherThanOverwrite(LendingTestSuite):
	def approve_twice(self, first, second):
		strategy = make_strategy(
			[
				rule(10, "bureau_score", ">", "600", "Approve", stop_on_match=0, **first),
				rule(20, "monthly_income", ">", "20000", "Approve", stop_on_match=0, **second),
			]
		)

		return evaluate_strategy(strategy.name, {"bureau_score": 712, "monthly_income": 60000})

	def test_a_looser_amount_cap_cannot_void_a_tighter_one(self):
		verdict = self.approve_twice({"term_amount_cap": 300000}, {"term_amount_cap": 600000})

		self.assertEqual(verdict.recommended_amount, 300000)

	def test_the_tighter_amount_cap_wins_whichever_order_it_matched_in(self):
		verdict = self.approve_twice({"term_amount_cap": 600000}, {"term_amount_cap": 300000})

		self.assertEqual(verdict.recommended_amount, 300000)

	def test_a_longer_tenure_cap_cannot_void_a_shorter_one(self):
		verdict = self.approve_twice({"term_tenure_cap": 24}, {"term_tenure_cap": 60})

		self.assertEqual(verdict.recommended_tenure, 24)

	def test_the_rate_keeps_the_one_that_prices_the_risk_higher(self):
		verdict = self.approve_twice({"term_roi_override": 15}, {"term_roi_override": 11})

		self.assertEqual(verdict.recommended_roi, 15)

	def test_the_term_that_was_passed_over_is_named_in_the_log(self):
		verdict = self.approve_twice({"term_amount_cap": 300000}, {"term_amount_cap": 600000})

		self.assertTrue(any("600000" in line for line in verdict.log))

	def test_a_different_outcome_still_drops_the_terms_it_supersedes(self):
		strategy = make_strategy(
			[
				rule(10, "bureau_score", ">", "600", "Approve", stop_on_match=0, term_amount_cap=300000),
				rule(20, "monthly_income", ">", "20000", "Refer", stop_on_match=0),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 712, "monthly_income": 60000})

		self.assertEqual(verdict.decision, "Refer")
		self.assertIsNone(verdict.recommended_amount)

class TestAnApplicationReachesTheLeadsBureauReport(LendingTestSuite):
	def test_a_report_filed_against_the_pan_is_found_at_underwriting(self):
		make_bureau_report(score=655, applicant=None, pan=TEST_PAN)
		lead = make_lead(pan=TEST_PAN, applicant_country="India")

		context = build_variable_context(make_application(loan_lead=lead.name))

		self.assertEqual(context["bureau_score"], 655)

	def test_a_report_against_the_applicant_is_still_preferred(self):
		make_bureau_report(score=655, applicant=None, pan=TEST_PAN)
		make_bureau_report(score=780)
		lead = make_lead(pan=TEST_PAN, applicant_country="India")

		context = build_variable_context(make_application(loan_lead=lead.name))

		self.assertEqual(context["bureau_score"], 780)

	def test_an_application_with_no_lead_finds_nothing_by_pan(self):
		make_bureau_report(score=655, applicant=None, pan=TEST_PAN)

		context = build_variable_context(make_application())

		self.assertNotIn("bureau_score", context)
