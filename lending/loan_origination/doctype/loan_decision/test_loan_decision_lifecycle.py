# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from lending.loan_origination import decisioning
from lending.loan_origination.decisioning import KNOCKOUT, UNDERWRITING
from lending.loan_origination.doctype.decision_strategy.test_decision_strategy import (
	make_reason,
	make_strategy,
	rule,
)
from lending.loan_origination.doctype.scorecard.test_scorecard import band, grade, make_scorecard
from lending.loan_origination.test_decisioning import (
	OTHER_LOAN_PRODUCT,
	TEST_LOAN_PRODUCT,
	make_application,
	make_bureau_report,
	make_lead,
)
from lending.tests.utils import LendingTestSuite


def approving_strategy(**terms):
	return make_strategy(
		[rule(10, "bureau_score", ">", "600", "Approve", **terms)],
		strategy_name="Test Underwriting Strategy",
		strategy_type=UNDERWRITING,
	)


def declining_strategy():
	return make_strategy(
		[rule(10, "bureau_score", "<", "600", "Decline", reason_code=make_reason())],
		strategy_name="Test Underwriting Strategy",
		strategy_type=UNDERWRITING,
	)


def scoring_scorecard():
	return make_scorecard(
		[band("bureau_score", 700, 900, 40)],
		grade_bands=[grade("B", 300, 359), grade("A", 360, 500)],
		base_score=300,
	)


@contextmanager
def no_read_permission_on(doctype):
	def has_permission(dt, ptype="read", *args, **kwargs):
		return not (dt == doctype and ptype == "read")

	with patch.object(frappe.permissions, "has_permission", side_effect=has_permission):
		yield


def row_for(comparison, strategy):
	rows = [row for row in comparison.rows if row.strategy == strategy]

	assert len(rows) == 1, f"{strategy} appears {len(rows)} times in the comparison"

	return rows[0]


def make_decision(application, strategy=None, scorecard=None):
	decision = frappe.new_doc("Loan Decision")
	decision.loan_application = application.name
	decision.strategy = strategy
	decision.scorecard = scorecard

	return decision.insert(ignore_permissions=True)












def income_approving_strategy():
	return make_strategy(
		[rule(10, "monthly_income", ">", "20000", "Approve")],
		strategy_name="Test Underwriting Strategy",
		strategy_type=UNDERWRITING,
	)


class TestAnUnscoredAttributeIsNotAnApproval(LendingTestSuite):
	def test_an_approve_over_an_unscored_attribute_becomes_refer(self):
		decision = make_decision(
			make_application(loan_lead=make_lead().name),
			income_approving_strategy().name,
			scoring_scorecard().name,
		)

		self.assertEqual(decision.decision, "Refer")
		self.assertIn("bureau_score", decision.decision_log)

	def test_an_approve_with_everything_scored_stays_approve(self):
		make_bureau_report(score=712)

		decision = make_decision(
			make_application(loan_lead=make_lead().name),
			income_approving_strategy().name,
			scoring_scorecard().name,
		)

		self.assertEqual(decision.decision, "Approve")

	def test_a_decline_is_not_promoted_by_an_unscored_attribute(self):
		decision = make_decision(
			make_application(loan_lead=make_lead().name),
			declining_strategy().name,
			scoring_scorecard().name,
		)

		self.assertIsNone(decision.decision)

class TestASubmittedDecisionIsTheOneThatWasReviewed(LendingTestSuite):
	def test_submitting_does_not_quietly_decide_again(self):
		make_bureau_report(score=712)
		decision = make_decision(
			make_application(loan_lead=make_lead().name), approving_strategy().name
		)
		self.assertEqual(decision.decision, "Approve")

		decision.submit()
		decision.reload()

		self.assertEqual(decision.decision, "Approve")
		self.assertEqual(decision.docstatus, 1)

	def test_an_application_that_moved_since_drafting_cannot_be_submitted(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		decision = make_decision(application, approving_strategy().name)

		application.db_set("loan_amount", application.loan_amount + 100000)

		with self.assertRaises(frappe.ValidationError):
			decision.submit()

	def test_saving_the_decision_again_lets_it_be_submitted(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		decision = make_decision(application, approving_strategy().name)

		application.db_set("loan_amount", application.loan_amount + 100000)
		decision.save()
		decision.submit()

		self.assertEqual(decision.docstatus, 1)

class TestTheBureauReportIsScopedOnTheServer(LendingTestSuite):
	def test_a_report_for_somebody_else_is_refused(self):
		somebody_else = make_bureau_report(score=800, applicant="_Test Loan Customer 2")
		application = make_application(loan_lead=make_lead().name)

		decision = frappe.new_doc("Loan Decision")
		decision.loan_application = application.name
		decision.bureau_report = somebody_else.name

		with self.assertRaises(frappe.ValidationError) as raised:
			decision.insert(ignore_permissions=True)

		self.assertIn(somebody_else.name, str(raised.exception))

	def test_a_draft_report_is_refused(self):
		draft = frappe.get_doc(
			{
				"doctype": "Credit Bureau Report",
				"applicant_type": "Customer",
				"applicant": "_Test Loan Customer",
				"bureau": "Manual",
				"score": 800,
				"total_emi": 0,
				"report_date": nowdate(),
			}
		).insert(ignore_permissions=True)

		application = make_application(loan_lead=make_lead().name)

		decision = frappe.new_doc("Loan Decision")
		decision.loan_application = application.name
		decision.bureau_report = draft.name

		with self.assertRaises(frappe.ValidationError):
			decision.insert(ignore_permissions=True)

	def test_the_applicant_own_report_is_still_accepted(self):
		report = make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)

		decision = frappe.new_doc("Loan Decision")
		decision.loan_application = application.name
		decision.bureau_report = report.name
		decision.insert(ignore_permissions=True)

		self.assertEqual(decision.bureau_report, report.name)
		self.assertEqual(decision.bureau_score, 712)

class TestTheSuppliedPoliciesAreScopedOnTheServer(LendingTestSuite):
	def test_a_disabled_strategy_is_refused(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		disabled = make_strategy(
			[rule(10, "bureau_score", ">", "600", "Approve")],
			strategy_name="Test Disabled Strategy",
			strategy_type=UNDERWRITING,
			disabled=1,
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			make_decision(application, strategy=disabled.name)

		self.assertIn(disabled.name, str(raised.exception))

	def test_a_strategy_of_another_stage_is_refused(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		knockout = make_strategy(
			[rule(10, "bureau_score", ">", "600", "Approve")],
			strategy_name="Test Knockout Strategy",
			strategy_type=KNOCKOUT,
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			make_decision(application, strategy=knockout.name)

		self.assertIn(knockout.name, str(raised.exception))

	def test_a_strategy_for_another_loan_product_is_refused(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		other_product = make_strategy(
			[rule(10, "bureau_score", ">", "600", "Approve")],
			strategy_name="Test Other Product Strategy",
			strategy_type=UNDERWRITING,
			loan_product=OTHER_LOAN_PRODUCT,
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			make_decision(application, strategy=other_product.name)

		self.assertIn(other_product.name, str(raised.exception))

	def test_a_scorecard_for_another_loan_product_is_refused(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		approving_strategy()
		other_product = make_scorecard(
			[band("bureau_score", 700, 900, 40)],
			scorecard_name="Test Other Product Scorecard",
			loan_product=OTHER_LOAN_PRODUCT,
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			make_decision(application, scorecard=other_product.name)

		self.assertIn(other_product.name, str(raised.exception))

	def test_comparing_against_a_policy_that_could_never_run_is_refused(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		disabled = make_strategy(
			[rule(10, "bureau_score", ">", "600", "Approve")],
			strategy_name="Test Disabled Strategy",
			strategy_type=UNDERWRITING,
			disabled=1,
		)

		self.assertRaises(
			frappe.ValidationError,
			decisioning.compare_strategies,
			application.name,
			strategy=disabled.name,
		)

	def test_a_policy_written_for_this_loan_product_is_still_accepted(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		strategy = make_strategy(
			[rule(10, "bureau_score", ">", "600", "Approve")],
			strategy_name="Test Personal Loan Strategy",
			strategy_type=UNDERWRITING,
			loan_product=TEST_LOAN_PRODUCT,
		)
		scorecard = make_scorecard(
			[band("bureau_score", 700, 900, 40)],
			scorecard_name="Test Personal Loan Scorecard",
			base_score=300,
			loan_product=TEST_LOAN_PRODUCT,
		)

		decision = make_decision(application, strategy=strategy.name, scorecard=scorecard.name)

		self.assertEqual(decision.decision, "Approve")
		self.assertEqual(decision.score, 340)

class TestADecisionOnlyGovernsAnOpenApplication(LendingTestSuite):
	def test_a_submitted_application_can_no_longer_be_decided(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)

		decision = make_decision(application, approving_strategy().name)
		application.submit()

		with self.assertRaises(frappe.ValidationError) as raised:
			decision.submit()

		self.assertIn("no longer a draft", str(raised.exception))

	def test_the_terms_on_the_submitted_application_are_left_alone(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)

		decision = make_decision(application, approving_strategy(term_amount_cap=100000).name)
		application.submit()

		with self.assertRaises(frappe.ValidationError):
			decision.submit()

		self.assertFalse(frappe.db.get_value("Loan Application", application.name, "decision"))
		self.assertFalse(
			frappe.db.get_value("Loan Application", application.name, "recommended_amount")
		)

	def test_a_draft_application_is_still_decided(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)

		decision = make_decision(application, approving_strategy().name)
		decision.submit()

		self.assertEqual(
			frappe.db.get_value("Loan Application", application.name, "decision"), decision.name
		)

	def test_a_decision_a_submitted_application_still_links_to_cannot_be_cancelled(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)

		decision = make_decision(application, approving_strategy().name)
		decision.submit()
		application.reload()
		application.submit()

		with self.assertRaises(frappe.LinkExistsError):
			decision.cancel()

	def test_cancelling_leaves_a_closed_application_as_it_was_decided(self):
		"""The link checks above keep a live decision and a live application tied to each
		other, so this state is only reached by stepping around them - a bulk cancel, a
		script that ignores links. The terms were still acted on, so they stay as they are.
		"""
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)

		decision = make_decision(application, approving_strategy(term_amount_cap=100000).name)
		decision.submit()
		application.reload()
		application.submit()
		application.flags.ignore_links = True
		application.cancel()

		decision.cancel()

		self.assertEqual(
			frappe.db.get_value("Loan Application", application.name, "decision"), decision.name
		)
		self.assertEqual(
			frappe.db.get_value("Loan Application", application.name, "recommended_amount"), 100000
		)

class TestTheComparisonHonoursTheForm(LendingTestSuite):
	def test_the_scorecard_on_the_form_is_the_one_scored(self):
		make_bureau_report(score=712)
		scoring_scorecard()
		chosen = make_scorecard(
			[band("bureau_score", 700, 900, 5)],
			grade_bands=[grade("Z", 0, 10000)],
			base_score=100,
			scorecard_name="Test Form Scorecard",
		)
		application = make_application(loan_lead=make_lead().name)
		approving_strategy()

		comparison = decisioning.compare_strategies(application.name, scorecard=chosen.name)

		self.assertEqual(comparison.scorecard, chosen.name)
		self.assertEqual(comparison.score, 105)
		self.assertEqual(comparison.grade, "Z")

	def test_the_bureau_report_on_the_form_is_the_one_compared_against(self):
		make_bureau_report(score=800)
		chosen = make_bureau_report(score=650)
		application = make_application(loan_lead=make_lead().name)
		approving_strategy()

		comparison = decisioning.compare_strategies(application.name, bureau_report=chosen.name)

		self.assertEqual(comparison.bureau_report, chosen.name)
		self.assertEqual(comparison.bureau_score, 650)

	def test_the_strategy_on_the_form_is_the_one_marked_selected(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		approving_strategy()
		runner_up = make_strategy(
			[rule(10, "bureau_score", ">", "600", "Refer")],
			strategy_name="Test Runner Up Strategy",
			strategy_type=UNDERWRITING,
			priority=1,
		)

		comparison = decisioning.compare_strategies(application.name, strategy=runner_up.name)

		self.assertEqual(comparison.selected, runner_up.name)
		self.assertTrue(row_for(comparison, runner_up.name).selected)

	def test_every_row_reports_its_own_verdict(self):
		make_bureau_report(score=712)
		application = make_application(loan_lead=make_lead().name)
		approving_strategy()
		make_strategy(
			[rule(10, "bureau_score", "<", "600", "Decline", reason_code=make_reason())],
			strategy_name="Test Never Matches Strategy",
			strategy_type=UNDERWRITING,
			priority=1,
		)

		comparison = decisioning.compare_strategies(application.name)

		self.assertEqual(row_for(comparison, "Test Underwriting Strategy").decision, "Approve")
		self.assertIsNone(row_for(comparison, "Test Never Matches Strategy").decision)
