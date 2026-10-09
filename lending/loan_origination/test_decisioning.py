# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors


import frappe
from frappe.utils import nowdate

from lending.loan_origination.decisioning import (
	KNOCKOUT,
	PRE_QUALIFICATION,
	build_variable_context,
	evaluate_strategy,
	run_strategy,
)
from lending.loan_origination.doctype.decision_strategy.test_decision_strategy import (
	make_reason,
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


class TestVariableContextFromALead(LendingTestSuite):
	def test_a_lead_supplies_the_applicant_variables(self):
		context = build_variable_context(make_lead())

		self.assertEqual(context["loan_amount"], 500000)
		self.assertEqual(context["tenure"], 36)
		self.assertEqual(context["monthly_income"], 60000)
		self.assertEqual(context["employment_type"], "Salaried")
		self.assertEqual(context["loan_product"], TEST_LOAN_PRODUCT)
		self.assertIn("age", context)

	def test_a_lead_finds_its_bureau_report_by_pan(self):
		make_bureau_report(score=540, total_emi=8000, pan=TEST_PAN)

		context = build_variable_context(make_lead(pan=TEST_PAN, applicant_country="India"))

		self.assertEqual(context["bureau_score"], 540)
		self.assertEqual(context["existing_obligations"], 8000)

	def test_a_lead_without_a_pan_has_no_bureau_score(self):
		make_bureau_report(score=540, pan=TEST_PAN)

		context = build_variable_context(make_lead())

		self.assertNotIn("bureau_score", context)

	def test_an_income_of_zero_is_unknown_rather_than_zero(self):
		context = build_variable_context(make_lead(income=0))

		self.assertNotIn("monthly_income", context)

class TestVariableContextFromAnApplication(LendingTestSuite):
	def test_an_application_supplies_its_own_variables(self):
		application = make_application()

		context = build_variable_context(application)

		self.assertEqual(context["loan_amount"], 500000)
		self.assertEqual(context["tenure"], 36)
		self.assertEqual(context["rate_of_interest"], application.rate_of_interest)
		self.assertEqual(context["proposed_emi"], application.repayment_amount)
		self.assertEqual(context["applicant_type"], "Customer")

	def test_applicant_variables_are_read_through_the_lead_link(self):
		lead = make_lead(income=75000, employment_type="Self-employed")

		context = build_variable_context(make_application(loan_lead=lead.name))

		self.assertEqual(context["monthly_income"], 75000)
		self.assertEqual(context["employment_type"], "Self-employed")

	def test_an_application_with_no_lead_has_no_applicant_variables(self):
		context = build_variable_context(make_application())

		self.assertNotIn("monthly_income", context)
		self.assertNotIn("employment_type", context)

	def test_a_bureau_report_supplies_the_score_and_the_obligations(self):
		make_bureau_report(score=712, total_emi=8000)

		context = build_variable_context(make_application(loan_lead=make_lead().name))

		self.assertEqual(context["bureau_score"], 712)
		self.assertEqual(context["existing_obligations"], 8000)
		self.assertAlmostEqual(context["dti_ratio"], 8000 / 60000)

	def test_obligations_of_zero_are_real_data_not_unknown(self):
		make_bureau_report(score=712, total_emi=0)

		context = build_variable_context(make_application(loan_lead=make_lead().name))

		self.assertEqual(context["existing_obligations"], 0)
		self.assertEqual(context["dti_ratio"], 0)

	def test_a_bureau_score_of_zero_is_unknown_rather_than_zero(self):
		make_bureau_report(score=0, total_emi=8000)

		context = build_variable_context(make_application())

		self.assertNotIn("bureau_score", context)
		self.assertEqual(context["existing_obligations"], 8000)

class TestUncollectedVariables(LendingTestSuite):
	def test_a_rule_on_an_uncollected_variable_does_not_fire(self):
		strategy = make_strategy(
			[rule(10, "monthly_income", "<", "20000", "Decline", reason_code=make_reason())]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 712})

		self.assertIsNone(verdict.decision)
		self.assertEqual(verdict.skipped_variables, ["monthly_income"])

	def test_the_skip_is_named_in_the_log(self):
		strategy = make_strategy(
			[rule(10, "monthly_income", "<", "20000", "Decline", reason_code=make_reason())]
		)

		verdict = evaluate_strategy(strategy.name, {})

		self.assertTrue(any("monthly_income" in line for line in verdict.log))

	def test_an_approve_is_downgraded_to_refer_when_a_rule_was_skipped(self):
		strategy = make_strategy(
			[
				rule(10, "monthly_income", "<", "20000", "Decline", reason_code=make_reason()),
				rule(20, "bureau_score", ">", "600", "Approve"),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 712})

		self.assertEqual(verdict.decision, "Refer")
		self.assertTrue(any("Refer" in line for line in verdict.log))

	def test_a_decline_on_collected_data_is_not_downgraded(self):
		strategy = make_strategy(
			[
				rule(10, "monthly_income", "<", "20000", "Refer", stop_on_match=0),
				rule(20, "bureau_score", "<", "600", "Decline", reason_code=make_reason()),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 500})

		self.assertEqual(verdict.decision, "Decline")

	def test_nothing_is_downgraded_when_nothing_was_skipped(self):
		strategy = make_strategy([rule(10, "bureau_score", ">", "600", "Approve")])

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 712})

		self.assertEqual(verdict.decision, "Approve")
		self.assertEqual(verdict.skipped_variables, [])

class TestKnockoutBlocksTheTransition(LendingTestSuite):
	def test_a_knockout_decline_throws_so_the_transition_rolls_back(self):
		make_strategy(
			[rule(10, "loan_amount", ">", "1000", "Decline", reason_code=make_reason())],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)

		with self.assertRaises(frappe.ValidationError):
			run_strategy(make_lead(), KNOCKOUT)

	def test_a_knockout_on_the_bureau_score_reaches_a_lead(self):
		make_bureau_report(score=540, pan=TEST_PAN)
		make_strategy(
			[rule(10, "bureau_score", "<", "600", "Decline", reason_code=make_reason())],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)

		with self.assertRaises(frappe.ValidationError):
			run_strategy(make_lead(pan=TEST_PAN, applicant_country="India"), KNOCKOUT)

	def test_a_knockout_approve_does_not_throw(self):
		make_strategy(
			[rule(10, "loan_amount", ">", "1000", "Approve")],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)

		verdict = run_strategy(make_lead(), KNOCKOUT)

		self.assertEqual(verdict.decision, "Approve")

	def test_no_strategy_means_no_verdict_and_no_throw(self):
		self.assertIsNone(run_strategy(make_lead(), "Underwriting-does-not-exist"))

class TestPreQualificationIsRecordedNotEnforced(LendingTestSuite):
	def prequalify(self, rules, **lead):
		make_strategy(
			rules, strategy_name="Test Pre-Qualification Strategy", strategy_type=PRE_QUALIFICATION
		)
		lead = make_lead(**lead)
		run_strategy(lead, PRE_QUALIFICATION)
		lead.reload()

		return lead

	def test_a_decline_is_recorded_on_the_lead_rather_than_thrown(self):
		reason = make_reason()

		lead = self.prequalify(
			[rule(10, "monthly_income", "<", "80000", "Decline", reason_code=reason)]
		)

		self.assertEqual(lead.prequalification_status, "Not Pre-Qualified")
		self.assertEqual(lead.prequalification_reason_codes, reason)
		self.assertIsNotNone(lead.prequalified_on)

	def test_a_declined_lead_is_still_free_to_convert(self):
		lead = self.prequalify(
			[rule(10, "monthly_income", "<", "80000", "Decline", reason_code=make_reason())]
		)

		self.assertEqual(lead.docstatus, 0)
		self.assertTrue(frappe.db.exists("Loan Lead", lead.name))

	def test_an_approve_reads_as_pre_qualified_not_as_approved(self):
		lead = self.prequalify([rule(10, "monthly_income", ">", "20000", "Approve")])

		self.assertEqual(lead.prequalification_status, "Pre-Qualified")

	def test_a_refer_is_recorded_as_referred(self):
		lead = self.prequalify([rule(10, "monthly_income", ">", "20000", "Refer")])

		self.assertEqual(lead.prequalification_status, "Referred")

	def test_the_indicative_terms_survive_on_the_lead(self):
		lead = self.prequalify(
			[
				rule(
					10,
					"monthly_income",
					">",
					"20000",
					"Approve",
					term_roi_override=11.5,
					term_amount_cap=300000,
					term_tenure_cap=24,
				)
			]
		)

		self.assertEqual(lead.indicative_roi, 11.5)
		self.assertEqual(lead.indicative_amount, 300000)
		self.assertEqual(lead.indicative_tenure, 24)

	def test_the_indicative_terms_are_named_in_the_comment_too(self):
		lead = self.prequalify(
			[rule(10, "monthly_income", ">", "20000", "Approve", term_roi_override=11.5)]
		)

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Loan Lead", "reference_name": lead.name},
			pluck="content",
		)

		self.assertTrue(any("11.5" in comment for comment in comments))

	def test_a_knockout_run_leaves_the_pre_qualification_fields_alone(self):
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve")],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)
		lead = make_lead()
		run_strategy(lead, KNOCKOUT)
		lead.reload()

		self.assertFalse(lead.prequalification_status)
