# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors

import json

import frappe
from frappe.utils import add_to_date, now_datetime, nowdate

from lending.loan_origination.decisioning import (
	ALLOWED_OPERATORS,
	APPROVE,
	KNOCKOUT,
	KNOWN_VARIABLES,
	PRE_QUALIFICATION,
	_cmp,
	build_variable_context,
	evaluate_strategy,
	run_strategy,
)
from lending.loan_origination.doctype.decision_strategy.test_decision_strategy import (
	TEST_PRIORITY,
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


class TestOperatorList(LendingTestSuite):
	def test_the_select_options_match_the_engine(self):
		options = frappe.get_meta("Decision Rule").get_field("operator").options.split("\n")

		self.assertEqual(
			sorted(option for option in options if option),
			sorted(ALLOWED_OPERATORS),
		)

	def test_the_variable_suggestions_match_the_engine(self):
		options = frappe.get_meta("Decision Rule").get_field("variable").options.split("\n")

		self.assertEqual(
			sorted(option for option in options if option),
			sorted(KNOWN_VARIABLES),
		)

	def test_every_suggested_variable_is_one_the_engine_can_produce(self):
		context = build_variable_context(make_application(loan_lead=make_lead().name))

		self.assertTrue(set(context).issubset(set(KNOWN_VARIABLES)), sorted(set(context) - set(KNOWN_VARIABLES)))

	def test_an_outcome_must_be_chosen(self):
		strategy = frappe.new_doc("Decision Strategy")
		strategy.strategy_name = "Outcome Required Strategy"
		strategy.strategy_type = "Underwriting"
		strategy.append("rules", {"sequence": 10, "variable": "age", "operator": "<", "value": "21"})

		with self.assertRaises(frappe.exceptions.MandatoryError):
			strategy.insert(ignore_permissions=True)

	def test_an_operator_the_engine_does_not_know_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_cmp(1, "**", 2)

class TestEqualityReadsBothKindsOfValue(LendingTestSuite):
	def test_two_numbers_are_compared_as_numbers(self):
		self.assertTrue(_cmp(700, "==", "700.0"))
		self.assertFalse(_cmp(700, "!=", "700.0"))

	def test_text_is_compared_as_text(self):
		self.assertTrue(_cmp("Salaried", "==", " Salaried "))
		self.assertTrue(_cmp("Salaried", "!=", "Self Employed"))

	def test_a_number_is_simply_not_equal_to_a_word(self):
		"""A rule may hold any variable against any value with == and !=, so the engine
		answers rather than throwing when only one side happens to be a number.
		"""
		self.assertFalse(_cmp(700, "==", "Not Available"))
		self.assertTrue(_cmp(700, "!=", "Not Available"))

	def test_such_a_rule_still_reaches_a_decision(self):
		strategy = make_strategy([rule(10, "bureau_score", "!=", "Not Available", "Approve")])

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 712})

		self.assertEqual(verdict.decision, APPROVE)

class TestVariableSnapshotIsSerialisable(LendingTestSuite):
	def test_the_context_survives_a_json_round_trip(self):
		context = build_variable_context(make_application(loan_lead=make_lead().name))

		self.assertEqual(json.loads(frappe.as_json(context)).keys(), context.keys())

class TestPriorityDecidesWhichStrategyRunsForALead(LendingTestSuite):
	def prequalify(self, lead=None):
		lead = lead or make_lead()
		verdict = run_strategy(lead, PRE_QUALIFICATION)
		lead.reload()

		return lead, verdict

	def test_the_highest_priority_strategy_is_the_one_that_decides_the_lead(self):
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Refer")],
			strategy_name="Test Lower Priority Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY,
		)
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve")],
			strategy_name="Test Higher Priority Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY + 10,
		)

		lead, verdict = self.prequalify()

		self.assertEqual(verdict.strategy, "Test Higher Priority Pre-Qualification")
		self.assertEqual(lead.prequalification_status, "Pre-Qualified")

	def test_the_losing_strategy_does_not_run_at_all(self):
		reason = make_reason()
		make_strategy(
			[
				rule(
					10,
					"monthly_income",
					">",
					"20000",
					"Decline",
					reason_code=reason,
					term_amount_cap=100000,
				)
			],
			strategy_name="Test Lower Priority Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY,
		)
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve", term_amount_cap=500000)],
			strategy_name="Test Higher Priority Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY + 10,
		)

		lead, _verdict = self.prequalify()

		self.assertEqual(lead.prequalification_status, "Pre-Qualified")
		self.assertFalse(lead.prequalification_reason_codes)
		self.assertEqual(lead.indicative_amount, 500000)

	def test_a_product_strategy_beats_a_generic_one_however_high_its_priority(self):
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Refer")],
			strategy_name="Test Generic Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY + 1000,
		)
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve")],
			strategy_name="Test Personal Loan Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			loan_product=TEST_LOAN_PRODUCT,
			priority=1,
		)

		lead, verdict = self.prequalify(make_lead(loan_product=TEST_LOAN_PRODUCT))

		self.assertEqual(verdict.strategy, "Test Personal Loan Pre-Qualification")
		self.assertEqual(lead.prequalification_status, "Pre-Qualified")

	def test_a_lead_on_another_product_falls_back_to_the_generic_pool(self):
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Refer")],
			strategy_name="Test Generic Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY + 1000,
		)
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve")],
			strategy_name="Test Personal Loan Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			loan_product=TEST_LOAN_PRODUCT,
			priority=1,
		)

		lead, verdict = self.prequalify(make_lead(loan_product=OTHER_LOAN_PRODUCT))

		self.assertEqual(verdict.strategy, "Test Generic Pre-Qualification")
		self.assertEqual(lead.prequalification_status, "Referred")

	def test_priority_does_not_reach_across_strategy_types(self):
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Decline", reason_code=make_reason())],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
			priority=TEST_PRIORITY + 1000,
		)
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve")],
			strategy_name="Test Pre-Qualification Strategy",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY,
		)

		lead, verdict = self.prequalify()

		self.assertEqual(verdict.strategy, "Test Pre-Qualification Strategy")
		self.assertEqual(lead.prequalification_status, "Pre-Qualified")

	def test_disabling_the_top_strategy_hands_the_run_to_the_next_one(self):
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Refer")],
			strategy_name="Test Disabled Top Priority",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY + 10,
			disabled=1,
		)
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve")],
			strategy_name="Test Live Pre-Qualification",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY,
		)

		lead, verdict = self.prequalify()

		self.assertEqual(verdict.strategy, "Test Live Pre-Qualification")
		self.assertEqual(lead.prequalification_status, "Pre-Qualified")

	def test_two_strategies_on_the_same_priority_are_broken_by_modified(self):
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Refer")],
			strategy_name="Test Tied Strategy A",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY,
		)
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve")],
			strategy_name="Test Tied Strategy B",
			strategy_type=PRE_QUALIFICATION,
			priority=TEST_PRIORITY,
		)

		frappe.db.set_value(
			"Decision Strategy", "Test Tied Strategy B", "modified", now_datetime(), update_modified=False
		)
		frappe.db.set_value(
			"Decision Strategy",
			"Test Tied Strategy A",
			"modified",
			add_to_date(now_datetime(), seconds=60),
			update_modified=False,
		)

		lead, verdict = self.prequalify()

		self.assertEqual(verdict.strategy, "Test Tied Strategy A")
		self.assertEqual(lead.prequalification_status, "Referred")

	def test_no_strategy_of_that_type_leaves_the_lead_undecided(self):
		make_strategy(
			[rule(10, "monthly_income", ">", "20000", "Approve")],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
			priority=TEST_PRIORITY,
		)

		frappe.db.set_value(
			"Decision Strategy",
			{"strategy_type": PRE_QUALIFICATION, "disabled": 0},
			"disabled",
			1,
		)

		lead, verdict = self.prequalify()

		self.assertIsNone(verdict)
		self.assertFalse(lead.prequalification_status)

class TestTheKnockoutGateFailsClosed(LendingTestSuite):
	def test_a_decline_that_could_not_be_checked_stops_the_transition(self):
		make_strategy(
			[rule(10, "bureau_score", "<", "600", "Decline", reason_code=make_reason())],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)

		# No bureau report for this applicant, so the rule that would reject them never runs.
		with self.assertRaises(frappe.ValidationError) as raised:
			run_strategy(make_lead(), KNOCKOUT)

		self.assertIn("bureau_score", str(raised.exception))

	def test_the_variable_that_was_missing_is_named(self):
		make_strategy(
			[rule(10, "bureau_score", "<", "600", "Decline", reason_code=make_reason())],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)

		verdict = evaluate_strategy("Test Knockout Strategy", {})

		self.assertEqual(verdict.unverified_declines, ["bureau_score"])

	def test_an_approve_that_could_not_be_checked_is_not_a_knockout(self):
		make_strategy(
			[rule(10, "bureau_score", ">", "600", "Approve")],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)

		verdict = run_strategy(make_lead(), KNOCKOUT)

		self.assertIsNone(verdict.decision)
		self.assertEqual(verdict.unverified_declines, [])

	def test_a_decline_on_data_that_was_collected_still_reads_as_a_decline(self):
		make_bureau_report(score=540, pan=TEST_PAN)
		make_strategy(
			[rule(10, "bureau_score", "<", "600", "Decline", reason_code=make_reason())],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			run_strategy(make_lead(pan=TEST_PAN, applicant_country="India"), KNOCKOUT)

		self.assertIn("declined", str(raised.exception))
