# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors

import frappe

from lending.loan_origination.decisioning import (
	KNOCKOUT,
	PRE_QUALIFICATION,
	UNDERWRITING,
	evaluate_strategy,
	select_strategy,
)
from lending.tests.utils import LendingTestSuite

TEST_REASON = "TEST_DECLINE_REASON"

TEST_PRIORITY = 100000


def make_reason(reason_code=TEST_REASON):
	if not frappe.db.exists("Adverse Action Reason", reason_code):
		frappe.get_doc(
			{
				"doctype": "Adverse Action Reason",
				"reason_code": reason_code,
				"description": "Raised by the decisioning test suite.",
			}
		).insert(ignore_permissions=True)

	return reason_code


def rule(sequence, variable, operator, value, outcome, reason_code=None, stop_on_match=1, **terms):
	row = {
		"sequence": sequence,
		"variable": variable,
		"operator": operator,
		"value": value,
		"outcome": outcome,
		"reason_code": reason_code,
		"stop_on_match": stop_on_match,
	}
	row.update(terms)

	return row


def make_strategy(
	rules,
	strategy_name="Test Decision Strategy",
	strategy_type=UNDERWRITING,
	loan_product=None,
	priority=TEST_PRIORITY,
	disabled=0,
):
	frappe.delete_doc(
		"Decision Strategy", strategy_name, force=True, ignore_permissions=True, ignore_missing=True
	)

	strategy = frappe.new_doc("Decision Strategy")
	strategy.strategy_name = strategy_name
	strategy.strategy_type = strategy_type
	strategy.loan_product = loan_product
	strategy.priority = priority
	strategy.disabled = disabled

	for row in rules:
		strategy.append("rules", row)

	return strategy.insert(ignore_permissions=True)


class TestDecisionStrategyEvaluation(LendingTestSuite):
	def test_the_first_matching_rule_wins_and_later_rules_do_not_run(self):
		strategy = make_strategy(
			[
				rule(10, "bureau_score", ">", "600", "Approve"),
				rule(20, "bureau_score", ">", "500", "Decline", reason_code=make_reason()),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 700})

		self.assertEqual(verdict.decision, "Approve")
		self.assertEqual(verdict.reason_codes, [])

	def test_sequence_orders_the_rules_not_row_position(self):
		strategy = make_strategy(
			[
				rule(20, "bureau_score", ">", "500", "Decline", reason_code=make_reason()),
				rule(10, "bureau_score", ">", "600", "Approve"),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 700})

		self.assertEqual(verdict.decision, "Approve")

	def test_clearing_stop_on_match_lets_a_later_rule_override(self):
		strategy = make_strategy(
			[
				rule(10, "bureau_score", ">", "600", "Approve", stop_on_match=0),
				rule(20, "loan_amount", ">", "1000000", "Refer"),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 700, "loan_amount": 2000000})

		self.assertEqual(verdict.decision, "Refer")

	def test_between_includes_both_bounds(self):
		strategy = make_strategy([rule(10, "bureau_score", "between", "600,750", "Approve")])

		for score in (600, 675, 750):
			with self.subTest(score=score):
				self.assertEqual(evaluate_strategy(strategy.name, {"bureau_score": score}).decision, "Approve")

		self.assertIsNone(evaluate_strategy(strategy.name, {"bureau_score": 751}).decision)

	def test_in_and_not_in_match_against_a_comma_separated_list(self):
		allowed = make_strategy(
			[rule(10, "employment_type", "in", "Salaried,Self-employed", "Approve")],
			strategy_name="Test In Strategy",
		)
		blocked = make_strategy(
			[rule(10, "employment_type", "not in", "Salaried,Self-employed", "Refer")],
			strategy_name="Test Not In Strategy",
		)

		self.assertEqual(evaluate_strategy(allowed.name, {"employment_type": "Salaried"}).decision, "Approve")
		self.assertIsNone(evaluate_strategy(allowed.name, {"employment_type": "Retired"}).decision)

		self.assertEqual(evaluate_strategy(blocked.name, {"employment_type": "Retired"}).decision, "Refer")
		self.assertIsNone(evaluate_strategy(blocked.name, {"employment_type": "Salaried"}).decision)

	def test_a_matched_rule_carries_its_recommended_terms(self):
		strategy = make_strategy(
			[
				rule(
					10,
					"bureau_score",
					">",
					"600",
					"Approve",
					term_roi_override=15,
					term_amount_cap=400000,
					term_tenure_cap=24,
				)
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 700})

		self.assertEqual(verdict.recommended_roi, 15)
		self.assertEqual(verdict.recommended_amount, 400000)
		self.assertEqual(verdict.recommended_tenure, 24)

	def test_a_declining_rule_carries_its_reason_code(self):
		strategy = make_strategy(
			[rule(10, "bureau_score", "<", "600", "Decline", reason_code=make_reason())]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 500})

		self.assertEqual(verdict.decision, "Decline")
		self.assertEqual(verdict.reason_codes, [TEST_REASON])


class TestDecisionStrategyValidation(LendingTestSuite):
	def test_a_decline_rule_without_a_reason_code_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy([rule(10, "bureau_score", "<", "600", "Decline")])

	def test_two_rules_cannot_share_a_sequence(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy(
				[
					rule(10, "bureau_score", ">", "600", "Approve"),
					rule(10, "loan_amount", ">", "100", "Refer"),
				]
			)

	def test_an_unsupported_operator_is_rejected_on_save(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy([rule(10, "bureau_score", "=~", "600", "Approve")])

	def test_a_between_rule_needs_two_values(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy([rule(10, "bureau_score", "between", "600", "Approve")])

	def test_a_between_rule_needs_numbers_for_its_bounds(self):
		for value in ("low,high", "600,high", "low,750"):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				make_strategy([rule(10, "bureau_score", "between", value, "Approve")])

	def test_a_between_rule_needs_its_bounds_the_right_way_round(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy([rule(10, "bureau_score", "between", "750,600", "Approve")])


class TestDecisionStrategySelection(LendingTestSuite):
	def test_a_disabled_strategy_is_never_selected(self):
		make_strategy(
			[rule(10, "bureau_score", ">", "600", "Approve")],
			strategy_name="Test Disabled Knockout",
			strategy_type=KNOCKOUT,
			disabled=1,
		)

		self.assertNotEqual(select_strategy(KNOCKOUT), "Test Disabled Knockout")


class TestRulesThatCouldNeverMatchAreRejected(LendingTestSuite):
	def test_a_variable_the_engine_does_not_produce_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy([rule(10, "bureau_scoer", "<", "600", "Approve")])

	def test_a_known_variable_still_saves(self):
		strategy = make_strategy([rule(10, "bureau_score", "<", "600", "Approve")])

		self.assertTrue(frappe.db.exists("Decision Strategy", strategy.name))

	def test_a_size_comparison_against_a_non_number_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy([rule(10, "monthly_income", ">", "100,000", "Approve")])

	def test_a_rule_that_got_past_validation_still_refuses_at_run_time(self):
		strategy = make_strategy([rule(10, "monthly_income", ">", "100000", "Approve")])
		frappe.db.set_value("Decision Rule", strategy.rules[0].name, "value", "100,000")

		with self.assertRaises(frappe.ValidationError):
			evaluate_strategy(strategy.name, {"monthly_income": 60000})

	def test_a_size_comparison_against_a_number_still_saves(self):
		strategy = make_strategy([rule(10, "monthly_income", ">", "100000", "Approve")])

		self.assertTrue(frappe.db.exists("Decision Strategy", strategy.name))

	def test_equality_against_a_word_is_left_alone(self):
		strategy = make_strategy([rule(10, "employment_type", "==", "Salaried", "Approve")])

		self.assertTrue(frappe.db.exists("Decision Strategy", strategy.name))

	def test_an_applicant_type_from_the_other_stage_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy(
				[rule(10, "applicant_type", "==", "Customer", "Approve")],
				strategy_type=PRE_QUALIFICATION,
			)

	def test_an_applicant_type_from_the_right_stage_saves(self):
		strategy = make_strategy(
			[rule(10, "applicant_type", "==", "Individual", "Approve")],
			strategy_type=PRE_QUALIFICATION,
		)

		self.assertTrue(frappe.db.exists("Decision Strategy", strategy.name))

	def test_the_underwriting_vocabulary_is_the_other_one(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy(
				[rule(10, "applicant_type", "==", "Individual", "Approve")],
				strategy_type=UNDERWRITING,
			)

	def test_each_value_of_an_in_list_is_checked(self):
		with self.assertRaises(frappe.ValidationError):
			make_strategy(
				[rule(10, "applicant_type", "in", "Individual,Employee", "Approve")],
				strategy_type=PRE_QUALIFICATION,
			)


class TestMembershipMatchesOnValueNotSpelling(LendingTestSuite):
	def test_a_numeric_in_list_matches_the_number(self):
		strategy = make_strategy([rule(10, "tenure", "in", "12,24,36", "Approve")])

		self.assertEqual(evaluate_strategy(strategy.name, {"tenure": 36.0}).decision, "Approve")

	def test_a_numeric_not_in_list_is_false_when_the_number_is_there(self):
		strategy = make_strategy([rule(10, "tenure", "not in", "12,24,36", "Refer")])

		self.assertIsNone(evaluate_strategy(strategy.name, {"tenure": 36.0}).decision)
		self.assertEqual(evaluate_strategy(strategy.name, {"tenure": 48.0}).decision, "Refer")

	def test_words_are_still_matched_as_words(self):
		strategy = make_strategy([rule(10, "employment_type", "in", "Salaried", "Approve")])

		self.assertEqual(
			evaluate_strategy(strategy.name, {"employment_type": "Salaried"}).decision, "Approve"
		)


class TestASupersedingRuleReplacesWhatCameBefore(LendingTestSuite):
	def test_a_decline_does_not_keep_an_earlier_approves_terms(self):
		strategy = make_strategy(
			[
				rule(
					10,
					"bureau_score",
					">",
					"600",
					"Approve",
					stop_on_match=0,
					term_roi_override=11.5,
					term_amount_cap=500000,
				),
				rule(20, "foir_ratio", ">", "0.55", "Decline", reason_code=make_reason()),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 700, "foir_ratio": 0.8})

		self.assertEqual(verdict.decision, "Decline")
		self.assertIsNone(verdict.recommended_roi)
		self.assertIsNone(verdict.recommended_amount)

	def test_an_approve_does_not_keep_an_earlier_declines_reason_code(self):
		strategy = make_strategy(
			[
				rule(
					10, "foir_ratio", ">", "0.55", "Decline", reason_code=make_reason(), stop_on_match=0
				),
				rule(20, "bureau_score", ">", "600", "Approve"),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 700, "foir_ratio": 0.8})

		self.assertEqual(verdict.decision, "Approve")
		self.assertEqual(verdict.reason_codes, [])

	def test_rules_that_agree_still_stack_their_reason_codes(self):
		second = make_reason("TEST_SECOND_DECLINE_REASON")
		strategy = make_strategy(
			[
				rule(
					10, "foir_ratio", ">", "0.55", "Decline", reason_code=make_reason(), stop_on_match=0
				),
				rule(20, "bureau_score", "<", "600", "Decline", reason_code=second),
			]
		)

		verdict = evaluate_strategy(strategy.name, {"bureau_score": 500, "foir_ratio": 0.8})

		self.assertEqual(verdict.decision, "Decline")
		self.assertEqual(sorted(verdict.reason_codes), sorted([TEST_REASON, second]))
