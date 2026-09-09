# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors

import frappe

from lending.loan_origination.decisioning import score_application
from lending.tests.utils import LendingTestSuite


def band(attribute, min_range, max_range, points):
	return {
		"attribute": attribute,
		"min_range": min_range,
		"max_range": max_range,
		"points": points,
	}


def grade(grade_name, min_score, max_score):
	return {"grade": grade_name, "min_score": min_score, "max_score": max_score}


def make_scorecard(
	attributes,
	grade_bands=None,
	scorecard_name="Test Scorecard",
	base_score=0,
	loan_product=None,
):
	frappe.delete_doc(
		"Scorecard", scorecard_name, force=True, ignore_permissions=True, ignore_missing=True
	)

	scorecard = frappe.new_doc("Scorecard")
	scorecard.scorecard_name = scorecard_name
	scorecard.base_score = base_score
	scorecard.loan_product = loan_product

	for row in attributes:
		scorecard.append("attributes", row)

	for row in grade_bands or [grade("A", 0, 10000)]:
		scorecard.append("grade_bands", row)

	return scorecard.insert(ignore_permissions=True)


class TestScorecardScoring(LendingTestSuite):
	def test_points_accumulate_onto_the_base_score(self):
		scorecard = make_scorecard(
			[band("bureau_score", 700, 900, 40), band("age", 25, 40, 10)],
			base_score=300,
		)

		scored = score_application(scorecard.name, {"bureau_score": 750, "age": 34})

		self.assertEqual(scored.score, 350)

	def test_a_value_outside_every_band_scores_nothing(self):
		scorecard = make_scorecard([band("bureau_score", 700, 900, 40)], base_score=300)

		scored = score_application(scorecard.name, {"bureau_score": 650})

		self.assertEqual(scored.score, 300)

	def test_band_bounds_are_inclusive(self):
		scorecard = make_scorecard([band("bureau_score", 700, 900, 40)])

		for score in (700, 900):
			with self.subTest(bureau_score=score):
				self.assertEqual(score_application(scorecard.name, {"bureau_score": score}).score, 40)

		self.assertEqual(score_application(scorecard.name, {"bureau_score": 901}).score, 0)

	def test_the_grade_comes_from_the_band_holding_the_total(self):
		scorecard = make_scorecard(
			[band("bureau_score", 700, 900, 40)],
			grade_bands=[grade("C", 0, 319), grade("B", 320, 359), grade("A", 360, 500)],
			base_score=300,
		)

		self.assertEqual(score_application(scorecard.name, {"bureau_score": 750}).grade, "B")
		self.assertEqual(score_application(scorecard.name, {"bureau_score": 100}).grade, "C")

	def test_a_total_outside_every_grade_band_is_ungraded(self):
		scorecard = make_scorecard(
			[band("bureau_score", 700, 900, 40)],
			grade_bands=[grade("A", 1000, 2000)],
			base_score=0,
		)

		self.assertIsNone(score_application(scorecard.name, {"bureau_score": 750}).grade)

	def test_an_uncollected_attribute_scores_nothing_and_is_reported(self):
		scorecard = make_scorecard(
			[band("bureau_score", 700, 900, 40), band("monthly_income", 50000, 999999, 20)],
			base_score=300,
		)

		scored = score_application(scorecard.name, {"bureau_score": 750})

		self.assertEqual(scored.score, 340)
		self.assertEqual(scored.uncollected, ["monthly_income"])
		self.assertTrue(any("monthly_income" in line for line in scored.log))

	def test_a_non_numeric_attribute_is_treated_as_uncollected(self):
		scorecard = make_scorecard([band("employment_type", 0, 100, 25)])

		scored = score_application(scorecard.name, {"employment_type": "Salaried"})

		self.assertEqual(scored.score, 0)
		self.assertEqual(scored.uncollected, ["employment_type"])


class TestScorecardValidation(LendingTestSuite):
	def test_an_attribute_the_engine_does_not_produce_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_scorecard([band("bureau_scoer", 600, 700, 20)])

	def test_a_variable_the_engine_produces_is_accepted(self):
		scorecard = make_scorecard([band("foir_ratio", 0, 1, 20)])

		self.assertEqual(scorecard.attributes[0].attribute, "foir_ratio")

	def test_overlapping_bands_on_one_attribute_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_scorecard([band("bureau_score", 600, 700, 20), band("bureau_score", 650, 750, 30)])

	def test_bands_on_different_attributes_may_overlap(self):
		scorecard = make_scorecard(
			[band("bureau_score", 600, 700, 20), band("age", 650, 750, 30)]
		)

		self.assertTrue(scorecard.name)

	def test_a_band_cannot_run_backwards(self):
		with self.assertRaises(frappe.ValidationError):
			make_scorecard([band("bureau_score", 900, 700, 20)])

	def test_overlapping_grade_bands_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_scorecard(
				[band("bureau_score", 700, 900, 40)],
				grade_bands=[grade("B", 300, 400), grade("A", 350, 500)],
			)

	def test_a_grade_band_cannot_run_backwards(self):
		with self.assertRaises(frappe.ValidationError):
			make_scorecard(
				[band("bureau_score", 700, 900, 40)],
				grade_bands=[grade("A", 500, 300)],
			)
