# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, nowdate

from lending.loan_management.doctype.loan.loan import create_dpd_record
from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
	create_process_loan_classification,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	loan_classification_ranges,
	make_loan_disbursement_entry,
)
from lending.tests.utils import LendingTestSuite


class TestCollectionCase(LendingTestSuite):
	def setUp(self):
		super().setUp()
		loan_classification_ranges()

	def create_overdue_loan(self):
		"""A disbursed loan whose first EMI (due 30 days after disbursement) is left unpaid past due date.

		update_days_past_due_in_loans only writes a Days Past Due Log once at least
		one Loan Repayment exists against the loan, so a token early repayment is
		made first to seed that, matching how the core DPD engine expects to be driven.

		Dates are anchored to nowdate() rather than hardcoded, since the DPD repost
		triggered by the seed repayment walks day-by-day from its value_date up to
		the real current date - a fixed historical date makes every test in this
		file slower every day that passes in real time. The whole timeline sits
		at least 40 days before nowdate() so that callers can still move a further
		30-40 days forward (classification/resolution dates) without landing in
		the future, matching the original 2024-03-06 -> 2024-05-11 span.
		"""
		posting_date = add_days(nowdate(), -70)
		repayment_start_date = add_days(nowdate(), -40)

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 1",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=12,
			applicant_type="Customer",
		)
		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date=posting_date, repayment_start_date=repayment_start_date
		)
		process_daily_loan_demands(posting_date=repayment_start_date, loan=loan.name)

		seed_repayment = create_repayment_entry(
			loan.name, add_days(repayment_start_date, 1), 100, loan_disbursement=disbursement.name
		)
		seed_repayment.submit()

		return loan, disbursement

	def test_case_opens_on_dpd_bucket_escalation(self):
		loan, _disbursement = self.create_overdue_loan()

		create_process_loan_classification(posting_date=add_days(nowdate(), -5), loan=loan.name)

		case = frappe.db.get_value(
			"Collection Case",
			{"loan": loan.name, "status": ("not in", ["Resolved", "Closed"])},
			["name", "status", "days_past_due", "bucket"],
			as_dict=1,
		)

		self.assertTrue(case)
		self.assertGreater(case.days_past_due, 0)
		self.assertEqual(case.status, "Open")

		self.assertTrue(
			frappe.db.exists(
				"Collection Case Log", {"loan": loan.name, "event": ("in", ["Case Opened", "Bucket Escalated"])}
			)
		)

	def test_case_resolves_when_dpd_returns_to_zero(self):
		loan, disbursement = self.create_overdue_loan()

		resolution_date = add_days(nowdate(), -5)
		create_process_loan_classification(posting_date=resolution_date, loan=loan.name)
		self.assertTrue(frappe.db.exists("Collection Case", {"loan": loan.name, "status": "Open"}))

		repayment_entry = create_repayment_entry(
			loan.name, resolution_date, 47523, loan_disbursement=disbursement.name
		)
		repayment_entry.submit()

		create_process_loan_classification(
			posting_date=add_days(resolution_date, 1), loan=loan.name, force_update_dpd_in_loan=1
		)

		case = frappe.db.get_value(
			"Collection Case", {"loan": loan.name}, ["status", "days_past_due"], as_dict=1, order_by="creation desc"
		)
		self.assertEqual(case.status, "Resolved")
		self.assertEqual(case.days_past_due, 0)

	def test_case_bucket_refreshes_on_de_escalation(self):
		"""A partial payment that lowers DPD into a less severe bucket (without
		clearing it to 0) must still update the open case's bucket/amounts, not
		just leave it stuck at the older, higher bucket.

		Driven directly via create_dpd_record (same as the re-escalation test
		below) rather than a real backdated repayment: create_overdue_loan()'s own
		seed repayment already reposts the loan's single unpaid demand all the way
		to today's real date, so any fixed-date repayment here would still land
		deep in the same bucket instead of crossing one.
		"""
		loan, disbursement = self.create_overdue_loan()

		last_log_date = frappe.db.get_value(
			"Collection Case Log", {"loan": loan.name}, "posting_date", order_by="posting_date desc"
		)
		day_1 = add_days(last_log_date, 1)
		day_2 = add_days(last_log_date, 2)

		create_dpd_record(loan.name, disbursement.name, day_1, 75)  # Doubtful 1 (61-90)
		case_before = frappe.db.get_value(
			"Collection Case", {"loan": loan.name, "status": "Open"}, ["name", "bucket", "days_past_due"], as_dict=1
		)
		self.assertEqual(case_before.bucket, "Doubtful 1")

		create_dpd_record(loan.name, disbursement.name, day_2, 45)  # Sub-Standard 2 (31-60)

		case_after = frappe.db.get_value(
			"Collection Case", case_before.name, ["status", "bucket", "days_past_due"], as_dict=1
		)
		self.assertEqual(case_after.status, "Open")
		self.assertEqual(case_after.bucket, "Sub-Standard 2")
		self.assertEqual(case_after.days_past_due, 45)

		self.assertTrue(
			frappe.db.exists(
				"Collection Case Log",
				{"loan": loan.name, "event": "Bucket De-escalated", "collection_case": case_before.name},
			)
		)

	def test_case_bucket_corrects_on_re_escalation_after_de_escalation(self):
		"""Escalate -> de-escalate -> re-escalate back to the same higher bucket.
		latest_log must pick up the de-escalation, or the re-escalation looks like
		"no change" against the stale pre-de-escalation bucket and the case is left
		showing the lower bucket while DPD has actually climbed back up.

		create_overdue_loan()'s seed repayment is itself backdated, so its own
		repost walks the DPD all the way up to today's real date before this test
		even starts (visible as a run of "Bucket Escalated" logs up to "Loss") --
		so the sequence below is layered on top of that, each step dated after the
		fixture's own last log, rather than trying to inject DPD readings earlier
		than what the fixture already produced (which the stale-history guard
		would then reject as older than what's on file).
		"""
		loan, disbursement = self.create_overdue_loan()

		last_log_date = frappe.db.get_value(
			"Collection Case Log", {"loan": loan.name}, "posting_date", order_by="posting_date desc"
		)
		day_1 = add_days(last_log_date, 1)
		day_2 = add_days(last_log_date, 2)
		day_3 = add_days(last_log_date, 3)

		create_dpd_record(loan.name, disbursement.name, day_1, 35)  # Sub-Standard 2 (31-60)
		case = frappe.db.get_value(
			"Collection Case", {"loan": loan.name, "status": "Open"}, ["name", "bucket"], as_dict=1
		)
		self.assertEqual(case.bucket, "Sub-Standard 2")

		create_dpd_record(loan.name, disbursement.name, day_2, 10)  # Sub-Standard 1 (1-30)
		self.assertEqual(frappe.db.get_value("Collection Case", case.name, "bucket"), "Sub-Standard 1")

		create_dpd_record(loan.name, disbursement.name, day_3, 35)  # back to Sub-Standard 2
		self.assertEqual(frappe.db.get_value("Collection Case", case.name, "bucket"), "Sub-Standard 2")
		self.assertEqual(frappe.db.get_value("Collection Case", case.name, "days_past_due"), 35)
