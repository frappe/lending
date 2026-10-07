# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

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
		"""A disbursed loan whose first EMI (due 2024-04-05) is left unpaid past due date.

		update_days_past_due_in_loans only writes a Days Past Due Log once at least
		one Loan Repayment exists against the loan, so a token early repayment is
		made first to seed that, matching how the core DPD engine expects to be driven.
		"""
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 1",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=12,
			applicant_type="Customer",
		)
		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		seed_repayment = create_repayment_entry(loan.name, "2024-04-06", 100, loan_disbursement=disbursement.name)
		seed_repayment.submit()

		return loan, disbursement

	def test_case_opens_on_dpd_bucket_escalation(self):
		loan, _disbursement = self.create_overdue_loan()

		create_process_loan_classification(posting_date="2024-05-10", loan=loan.name)

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

		create_process_loan_classification(posting_date="2024-05-10", loan=loan.name)
		self.assertTrue(frappe.db.exists("Collection Case", {"loan": loan.name, "status": "Open"}))

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-10", 47523, loan_disbursement=disbursement.name
		)
		repayment_entry.submit()

		create_process_loan_classification(
			posting_date="2024-05-11", loan=loan.name, force_update_dpd_in_loan=1
		)

		case = frappe.db.get_value(
			"Collection Case", {"loan": loan.name}, ["status", "days_past_due"], as_dict=1, order_by="creation desc"
		)
		self.assertEqual(case.status, "Resolved")
		self.assertEqual(case.days_past_due, 0)

	def test_case_bucket_refreshes_on_de_escalation(self):
		"""A partial payment that lowers DPD into a less severe bucket (without
		clearing it to 0) must still update the open case's bucket/amounts, not
		just leave it stuck at the older, higher bucket."""
		loan, disbursement = self.create_overdue_loan()
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		create_process_loan_classification(posting_date="2024-06-10", loan=loan.name)
		case_before = frappe.db.get_value(
			"Collection Case", {"loan": loan.name, "status": "Open"}, ["name", "bucket", "days_past_due"], as_dict=1
		)
		self.assertTrue(case_before)
		self.assertGreater(case_before.days_past_due, 30)

		# Clears only the oldest (April) EMI, leaving the May EMI still overdue --
		# DPD should drop to date_diff(today, May EMI due date), not to 0.
		repayment_entry = create_repayment_entry(
			loan.name, "2024-06-10", 44425, loan_disbursement=disbursement.name
		)
		repayment_entry.submit()

		create_process_loan_classification(
			posting_date="2024-06-11", loan=loan.name, force_update_dpd_in_loan=1
		)

		case_after = frappe.db.get_value(
			"Collection Case", case_before.name, ["status", "bucket", "days_past_due"], as_dict=1
		)
		self.assertEqual(case_after.status, "Open")
		self.assertLess(case_after.days_past_due, case_before.days_past_due)
		self.assertNotEqual(case_after.bucket, case_before.bucket)

		self.assertTrue(
			frappe.db.exists(
				"Collection Case Log",
				{"loan": loan.name, "event": "Bucket De-escalated", "collection_case": case_before.name},
			)
		)
