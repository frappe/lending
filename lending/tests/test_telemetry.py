from unittest.mock import patch

import frappe

from lending import hooks
from lending.telemetry import (
	CONVERSION_EVENT,
	CREATION_MILESTONES,
	FIRST_CAPTURE_MILESTONE,
	MILESTONE_DOCTYPE,
	PROCESS_MILESTONES,
	SUBMIT_EVENTS,
	capture,
	capture_charge_applied,
	capture_daily_portfolio_pulse,
	capture_first,
	capture_loan_closure,
	on_collection_case_insert,
	on_loan_npa_log_insert,
	on_loan_repayment_submit,
	on_loan_submit,
	on_milestone_insert,
	on_process_submit,
	on_submit_event,
	sanitize_properties,
)
from lending.tests.utils import LendingTestSuite


class TestLendingTelemetry(LendingTestSuite):
	def setUp(self):
		self.captured = []

		def collect(event, app, properties=None):
			self.captured.append((event, properties or {}))

		# Tests are a skipped context by design, and `_capture` would talk to the
		# real provider, so stub both to exercise the surrounding logic.
		patches = [
			patch("lending.telemetry._skip_context", return_value=False),
			patch("lending.telemetry.is_enabled", return_value=True),
			patch("lending.telemetry._capture", side_effect=collect),
			patch("lending.telemetry.site_age", return_value=3),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def events(self, name):
		return [props for event, props in self.captured if event == name]

	def release(self, *events):
		for event in events:
			frappe.db.delete(MILESTONE_DOCTYPE, {"event": event})

	def test_loan_booked_carries_flags_and_no_identity(self):
		self.release("first_loan_booked")
		doc = frappe._dict(
			applicant_type="Customer",
			repayment_method="Repay Over Number of Periods",
			repayment_frequency="Monthly",
			repayment_periods=12,
			is_term_loan=1,
			is_secured_loan=0,
			loan_application="LA-1",
			loan_partner=None,
			is_imported=0,
			applicant="CUST-SECRET",
			loan_amount=500000,
		)
		on_loan_submit(doc)

		props = self.events("loan_booked")[0]
		self.assertEqual(props["repayment_periods"], 12)
		self.assertTrue(props["from_application"])
		self.assertFalse(props["has_partner"])
		self.assertNotIn("applicant", props)
		self.assertNotIn("loan_amount", props)
		self.assertEqual(len(self.events("first_loan_booked")), 1)

	def test_milestone_fires_once(self):
		self.release("first_repayment_received")
		doc = frappe._dict(repayment_type="Normal Repayment")
		on_loan_repayment_submit(doc)
		on_loan_repayment_submit(doc)

		self.assertEqual(len(self.events("loan_repayment_received")), 2)
		first = self.events("first_repayment_received")
		self.assertEqual(len(first), 1)
		self.assertEqual(first[0]["day_since_install"], 3)

	def test_milestone_skipped_on_old_site(self):
		self.release("first_loan_disbursed")
		with patch("lending.telemetry.site_age", return_value=90):
			capture_first("first_loan_disbursed")

		self.assertEqual(self.captured, [])
		self.assertFalse(frappe.db.exists(MILESTONE_DOCTYPE, "first_loan_disbursed"))

	def test_setup_doc_insert_fires_creation_milestone(self):
		self.release(CREATION_MILESTONES["Loan Product"])
		on_milestone_insert(frappe._dict(doctype="Loan Product"))
		self.assertEqual(len(self.events("first_loan_product_created")), 1)

	def test_conversion_after_window(self):
		self.release(CONVERSION_EVENT, FIRST_CAPTURE_MILESTONE)
		capture("_test_usage")
		frappe.db.set_value(MILESTONE_DOCTYPE, FIRST_CAPTURE_MILESTONE, "creation", "2000-01-01 10:00:00")
		capture("_test_usage")

		self.assertEqual(len(self.events(CONVERSION_EVENT)), 1)
		capture("_test_usage")
		self.assertEqual(len(self.events(CONVERSION_EVENT)), 1)

	def test_nothing_captured_when_disabled(self):
		self.release("first_loan_booked", CONVERSION_EVENT, FIRST_CAPTURE_MILESTONE)
		self.captured.clear()

		with patch("lending.telemetry.is_enabled", return_value=False):
			capture("_test_usage")
			on_loan_submit(frappe._dict())
			capture_daily_portfolio_pulse()

		self.assertEqual(self.captured, [])
		self.assertFalse(frappe.db.exists(MILESTONE_DOCTYPE, FIRST_CAPTURE_MILESTONE))
		self.assertFalse(frappe.db.exists(MILESTONE_DOCTYPE, "first_loan_booked"))

	def test_hook_failure_never_raises(self):
		with patch("lending.telemetry.capture", side_effect=RuntimeError("boom")):
			on_loan_submit(frappe._dict())

	def test_only_scalars_and_fixed_vocabulary_leave_the_site(self):
		clean = sanitize_properties(
			{
				"count": 3,
				"flag": True,
				"missing": None,
				"note": "free text",
				"applicant_name": "Jane Doe",
				"nested": {"a": 1},
				"repayment_type": "Normal Repayment",
				"repayment_frequency": "Fortnightly-custom",
			}
		)
		self.assertEqual(
			clean,
			{
				"count": 3,
				"flag": True,
				"missing": None,
				"repayment_type": "Normal Repayment",
				"repayment_frequency": "other",
			},
		)

	def stub_portfolio_counts(self):
		self.count_filters = {}
		counts = {"Loan": 5, "Loan Disbursement": 3, "Loan Repayment": 4, "Loan Demand": 6}

		def fake_count(doctype, filters=None, *args, **kwargs):
			self.count_filters[doctype] = filters
			if doctype == "Loan" and "is_npa" in filters:
				return 1
			if doctype == "Loan" and "days_past_due" in filters:
				return 2
			return counts[doctype]

		return patch("frappe.db.count", side_effect=fake_count)

	def test_daily_pulse_sends_one_summary_of_yesterday(self):
		with patch("lending.telemetry.today", return_value="2026-03-12"), self.stub_portfolio_counts():
			capture_daily_portfolio_pulse()

		summaries = self.events("portfolio_daily_summary")
		self.assertEqual(len(summaries), 1)
		self.assertEqual(
			summaries[0],
			{
				"active_loans": 5,
				"npa_loans": 1,
				"overdue_loans": 2,
				"disbursements": 3,
				"repayments": 4,
				"demands_raised": 6,
				# 2026-03-11 is a Wednesday, Monday is 0
				"weekday": 2,
			},
		)
		self.assertEqual(self.count_filters["Loan Repayment"]["posting_date"], "2026-03-11")
		self.assertEqual(self.count_filters["Loan Demand"]["demand_date"], "2026-03-11")

	def test_daily_pulse_is_silent_without_active_loans(self):
		with patch("frappe.db.count", return_value=0):
			capture_daily_portfolio_pulse()

		self.assertEqual(self.events("portfolio_daily_summary"), [])

	def fail_only_for(self, target):
		"""Stub `_capture` to raise for one event. Records whether that event's claim
		existed at the moment of the send, so the test proves it got that far."""
		self.claim_held_during_send = None

		def collect_or_fail(event, app, properties=None):
			if event == target:
				self.claim_held_during_send = bool(frappe.db.exists(MILESTONE_DOCTYPE, target))
				raise RuntimeError("provider down")
			self.captured.append((event, properties or {}))

		return patch("lending.telemetry._capture", side_effect=collect_or_fail)

	def start_conversion_clock(self):
		self.release(CONVERSION_EVENT, FIRST_CAPTURE_MILESTONE)
		capture("_test_usage")
		frappe.db.set_value(MILESTONE_DOCTYPE, FIRST_CAPTURE_MILESTONE, "creation", "2000-01-01 10:00:00")

	def test_failed_send_gives_the_claim_back(self):
		self.release("first_loan_booked")

		with self.fail_only_for("first_loan_booked"):
			on_loan_submit(frappe._dict())

		self.assertTrue(self.claim_held_during_send)
		self.assertFalse(frappe.db.exists(MILESTONE_DOCTYPE, "first_loan_booked"))

		on_loan_submit(frappe._dict())
		self.assertEqual(len(self.events("first_loan_booked")), 1)

	def test_failed_conversion_send_can_be_retried(self):
		self.start_conversion_clock()

		with self.fail_only_for(CONVERSION_EVENT), self.assertRaises(RuntimeError):
			capture("_test_usage")

		self.assertTrue(self.claim_held_during_send)
		self.assertFalse(frappe.db.exists(MILESTONE_DOCTYPE, CONVERSION_EVENT))

		capture("_test_usage")
		self.assertEqual(len(self.events(CONVERSION_EVENT)), 1)

	def test_failed_conversion_does_not_resend_a_sent_milestone(self):
		self.release("first_loan_disbursed")
		self.start_conversion_clock()

		with self.fail_only_for(CONVERSION_EVENT), self.assertRaises(RuntimeError):
			capture_first("first_loan_disbursed")

		self.assertEqual(len(self.events("first_loan_disbursed")), 1)
		self.assertTrue(frappe.db.exists(MILESTONE_DOCTYPE, "first_loan_disbursed"))

		capture_first("first_loan_disbursed")
		self.assertEqual(len(self.events("first_loan_disbursed")), 1)

	def test_table_driven_submit_event(self):
		self.release("first_credit_bureau_report_pulled")
		doc = frappe._dict(
			doctype="Credit Bureau Report", bureau="CIBIL", applicant_type="Customer", obligations_known=1, applicant="SECRET"
		)
		on_submit_event(doc)

		props = self.events("credit_bureau_report_pulled")[0]
		self.assertEqual(props, {"bureau": "CIBIL", "applicant_type": "Customer", "obligations_known": True})
		self.assertEqual(len(self.events("first_credit_bureau_report_pulled")), 1)

	def test_unknown_vocabulary_value_is_coarsened(self):
		on_submit_event(frappe._dict(doctype="Credit Bureau Report", bureau="My Custom Bureau Ltd"))
		self.assertEqual(self.events("credit_bureau_report_pulled")[0]["bureau"], "other")

	def test_process_run_does_not_drive_conversion(self):
		self.release("first_interest_accrual_run", FIRST_CAPTURE_MILESTONE, CONVERSION_EVENT)
		on_process_submit(frappe._dict(doctype="Process Loan Interest Accrual"))

		self.assertEqual(len(self.events("first_interest_accrual_run")), 1)
		self.assertFalse(frappe.db.exists(MILESTONE_DOCTYPE, FIRST_CAPTURE_MILESTONE))

	def test_loan_closure_events(self):
		self.release("first_loan_closed")
		capture_loan_closure(requested=True)
		self.assertEqual(self.events("loan_closure")[0], {"closure": "requested"})
		self.assertEqual(self.events("first_loan_closed"), [])

		capture_loan_closure(requested=False)
		self.assertEqual(self.events("loan_closure")[1], {"closure": "closed"})
		self.assertEqual(len(self.events("first_loan_closed")), 1)

	def test_npa_and_collection_case_events(self):
		self.release("first_collection_case_opened")
		on_loan_npa_log_insert(frappe._dict(npa=1, manual_npa=0, delinked=0))
		on_collection_case_insert(frappe._dict(applicant_type="Customer", status="Open"))

		self.assertEqual(self.events("loan_npa_status_changed")[0]["is_npa"], True)
		self.assertEqual(self.events("collection_case_opened")[0]["status"], "Open")
		self.assertEqual(len(self.events("first_collection_case_opened")), 1)

	def test_charge_applied_never_sends_amount(self):
		capture_charge_applied("Flat")
		self.assertEqual(self.events("loan_charge_applied")[0], {"based_on": "Flat"})

	def test_every_telemetry_hook_resolves_to_a_real_function(self):
		for doctype, events in hooks.doc_events.items():
			for method in events.values():
				for path in [method] if isinstance(method, str) else method:
					if path.startswith("lending.telemetry."):
						self.assertTrue(callable(frappe.get_attr(path)), path)

		for path in hooks.scheduler_events["daily"]:
			self.assertTrue(callable(frappe.get_attr(path)), path)

	def test_every_table_entry_is_hooked(self):
		hooked = {dt for dt, ev in hooks.doc_events.items() if "lending.telemetry." in str(ev)}
		for doctype in [*SUBMIT_EVENTS, *PROCESS_MILESTONES, *CREATION_MILESTONES]:
			self.assertIn(doctype, hooked, doctype)
			self.assertTrue(frappe.db.exists("DocType", doctype), doctype)
