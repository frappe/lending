# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import flt, getdate

from lending.loan_management.doctype.loan_installment_skip_request.loan_installment_skip_request import (
	get_upcoming_installments,
	skip_installments,
)
from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_restructure.test_loan_restructure import (
	create_loan_restructure,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	make_loan_disbursement_entry,
	set_loan_accrual_frequency,
)
from lending.tests.utils import LendingTestSuite


class InstallmentSkipTestCase(LendingTestSuite):
	"""Every test starts from the same loan: first EMI paid, interest accrued till 19 Oct.
	It is built once per class and each test rolls back to it."""

	@classmethod
	def make_class_data(cls):
		cls.loan = make_loan_with_first_emi_paid().name


class TestLoanInstallmentSkipRequest(InstallmentSkipTestCase):
	def test_named_approver_approves_and_cancelling_restores_the_schedule(self):
		loan = frappe.get_doc("Loan", self.loan)
		approver = make_user("skip.approver@example.com", ["Accounts User"])
		frappe.db.set_value("Loan", loan.name, "installment_skip_approver", approver)
		old_schedule = get_active_schedule(loan.name)

		request = make_request(loan.name, ["2026-11-07"])

		# Open until it is decided. The approver comes from the Loan and the requester cannot change it
		self.assertEqual((request.docstatus, request.status, request.approver), (0, "Open", approver))
		request.approver = "Administrator"
		request.save()
		self.assertEqual(request.approver, approver)
		self.assertFalse(request.loan_restructure)
		self.assertEqual(get_active_schedule(loan.name).name, old_schedule.name)

		# The approver has no lending role. The request and the loan are shared with them
		request = frappe.get_doc("Loan Installment Skip Request", request.name)
		request.status = "Approved"
		frappe.set_user(approver)
		try:
			request.submit()
		finally:
			frappe.set_user("Administrator")

		request.reload()
		self.assertEqual((request.docstatus, request.status), (1, "Approved"))

		restructure = frappe.get_doc("Loan Restructure", request.loan_restructure)
		self.assertEqual((restructure.restructure_type, restructure.status), ("Installment Skip", "Approved"))
		self.assertEqual(restructure.loan_installment_skip_request, request.name)

		skipped_row = get_row(get_active_schedule(loan.name), "2026-11-07")
		self.assertEqual((skipped_row.total_payment, skipped_row.demand_generated), (0, 1))

		request.cancel()

		request.reload()
		self.assertEqual(request.status, "Cancelled")
		self.assertEqual(frappe.db.get_value("Loan Restructure", request.loan_restructure, "docstatus"), 2)
		self.assertEqual(get_active_schedule(loan.name).name, old_schedule.name)

	def test_who_can_reject_and_approve_a_request(self):
		loan = frappe.get_doc("Loan", self.loan)
		approver = make_user("skip.approver@example.com", ["Accounts User"])
		other_user = make_user("skip.other@example.com", ["Accounts User"])
		manager = make_user("skip.manager@example.com", ["Loan Manager"])
		frappe.db.set_value("Loan", loan.name, "installment_skip_approver", approver)

		# A rejected request keeps the schedule and does not block a new request
		request = make_request(loan.name, ["2026-11-07"])
		request.status = "Rejected"
		request.approver_remarks = "Not allowed this month"
		request.submit()

		request.reload()
		self.assertEqual((request.docstatus, request.status), (1, "Rejected"))
		self.assertFalse(request.loan_restructure)
		self.assertTrue(get_row(get_active_schedule(loan.name), "2026-11-07").total_payment > 0)

		# Only the named approver or a Loan Manager can decide
		request = make_request(loan.name, ["2026-11-07"])
		request.status = "Approved"
		frappe.set_user(other_user)
		try:
			self.assertRaises((frappe.PermissionError, frappe.ValidationError), request.submit)
		finally:
			frappe.set_user("Administrator")

		# A Loan Manager can decide without being the named approver
		request = frappe.get_doc("Loan Installment Skip Request", request.name)
		request.status = "Approved"
		frappe.set_user(manager)
		try:
			request.submit()
		finally:
			frappe.set_user("Administrator")

		request.reload()
		self.assertTrue(request.loan_restructure)

		# The requester cannot approve their own request, even as a Loan Manager
		frappe.set_user(manager)
		try:
			own_request = make_request(loan.name, ["2026-12-07"])
			own_request.status = "Approved"
			self.assertRaises(frappe.ValidationError, own_request.submit)
		finally:
			frappe.set_user("Administrator")

	def test_request_is_approved_at_once_when_approval_is_not_needed(self):
		loan = frappe.get_doc("Loan", self.loan)
		frappe.db.set_value("Loan Product", loan.loan_product, "installment_skip_needs_approval", 0)

		request = make_request(loan.name, ["2026-11-07"])

		request.reload()
		self.assertEqual((request.docstatus, request.status), (1, "Approved"))
		self.assertEqual(frappe.db.get_value("Loan Restructure", request.loan_restructure, "status"), "Approved")

	def test_request_is_checked_when_raised_and_when_approved(self):
		loan = frappe.get_doc("Loan", self.loan)

		# A loan that is not fully disbursed cannot skip
		frappe.db.set_value("Loan", loan.name, "status", "Partially Disbursed")
		self.assertRaises(frappe.ValidationError, make_request, loan.name, ["2026-11-07"])
		frappe.db.set_value("Loan", loan.name, "status", "Disbursed")

		# A user without access to the loan cannot raise a request
		stranger = make_user("skip.stranger@example.com", ["Accounts User"])
		frappe.set_user(stranger)
		try:
			self.assertRaises(frappe.PermissionError, make_request, loan.name, ["2026-11-07"])
		finally:
			frappe.set_user("Administrator")

		# The same installment cannot be in two requests
		request = make_request(loan.name, ["2026-11-07"])
		self.assertRaises(frappe.ValidationError, make_request, loan.name, ["2026-11-07", "2026-12-07"])

		# A demand generated after the request stops the approval, and the request stays open
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-11-07")
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")

		# A failed request is rolled back, as it is when it comes from the browser
		frappe.db.savepoint("approval")
		self.assertRaises(frappe.ValidationError, approve, request)
		frappe.db.rollback(save_point="approval")

		request.reload()
		self.assertEqual((request.docstatus, request.status), (0, "Open"))
		self.assertFalse(request.loan_restructure)

		# An installment that has a demand cannot be requested
		request.status = "Rejected"
		request.submit()
		self.assertRaises(frappe.ValidationError, make_request, loan.name, ["2026-11-07"])

		# Demands generated for a request that fails are not kept
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-11-10")
		demands = frappe.db.count("Loan Demand", {"loan": loan.name})
		self.assertRaises(
			frappe.ValidationError,
			skip_installments,
			loan.name,
			'["2026-11-08"]',
			restructure_date="2026-11-11",
		)
		self.assertEqual(frappe.db.count("Loan Demand", {"loan": loan.name}), demands)


class TestInstallmentSkipRestructure(InstallmentSkipTestCase):
	"""The Loan Restructure of type Installment Skip, which does the work for an approved request"""

	def test_installment_skip_rebuilds_schedule_and_skips_the_demand(self):
		loan = frappe.get_doc("Loan", self.loan)

		old_schedule = get_active_schedule(loan.name)
		pending_principal = (
			old_schedule.repayment_schedule[2].balance_loan_amount + old_schedule.repayment_schedule[2].principal_amount
		)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07"],
		)
		self.assertEqual(loan_restructure.status, "Initiated")

		loan_restructure.status = "Approved"
		loan_restructure.save()

		new_schedule = get_active_schedule(loan.name)
		first_row = get_row(new_schedule, "2026-11-07")

		self.assertEqual(frappe.db.get_value("Loan Repayment Schedule", old_schedule.name, "status"), "Rescheduled")
		self.assertEqual((first_row.principal_amount, first_row.interest_amount, first_row.total_payment), (0, 0, 0))
		self.assertEqual(first_row.demand_generated, 1)

		# Same EMI, so the maturity moves by one period
		self.assertEqual(new_schedule.monthly_repayment_amount, old_schedule.monthly_repayment_amount)
		self.assertEqual(len(new_schedule.repayment_schedule), len(old_schedule.repayment_schedule) + 1)
		self.assertEqual(getdate(new_schedule.repayment_schedule[-1].payment_date), getdate("2027-04-07"))

		# Principal is fully repaid and the skipped interest is added to the next installment demand
		rebuilt_rows = [row for row in new_schedule.repayment_schedule if getdate(row.payment_date) >= getdate("2026-11-07")]
		self.assertEqual(flt(sum(row.principal_amount for row in rebuilt_rows), 2), flt(pending_principal, 2))
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)
		# Interest of Oct 7 to Dec 7 (daily accruals add a few paise of rounding)
		self.assertAlmostEqual(
			next_row(new_schedule, "2026-11-07").interest_amount,
			first_row.balance_loan_amount * 12 * 61 / 36500,
			delta=0.5,
		)

		# Like a Pre Payment schedule, it keeps every earlier row and the loan's own start date
		self.assertEqual(new_schedule.repayment_start_date, old_schedule.repayment_start_date)
		self.assertEqual(
			[(row.payment_date, row.demand_generated) for row in new_schedule.repayment_schedule[:2]],
			[(row.payment_date, row.demand_generated) for row in old_schedule.repayment_schedule[:2]],
		)

		# The skipped installment gets no demand and is never overdue
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-20")
		self.assertEqual(get_demand_dates(loan.name).count(getdate("2026-11-07")), 0)
		self.assertEqual(calculate_amounts(loan.name, "2026-11-20")["payable_amount"], 0)
		loan.load_from_db()
		self.assertEqual(loan.days_past_due, 0)

		# Next installment demand is raised once, with the skipped interest
		process_daily_loan_demands(loan=loan.name, posting_date="2026-12-07")
		self.assertEqual(get_demand_dates(loan.name).count(getdate("2026-12-07")), 2)
		self.assertEqual(
			calculate_amounts(loan.name, "2026-12-07")["payable_amount"],
			next_row(new_schedule, "2026-11-07").total_payment,
		)

	def test_installment_skip_of_several_installments_including_the_last(self):
		loan = frappe.get_doc("Loan", self.loan)
		old_schedule = get_active_schedule(loan.name)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07", "2027-01-07", "2027-03-07"],
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		new_schedule = get_active_schedule(loan.name)
		skipped_rows = [row for row in new_schedule.repayment_schedule if not row.total_payment]

		# Same EMI, so every skipped installment, the last one too, adds a period at the end
		self.assertEqual(
			[getdate(row.payment_date) for row in skipped_rows],
			[getdate("2026-11-07"), getdate("2027-01-07"), getdate("2027-03-07")],
		)
		self.assertTrue(all(row.demand_generated for row in skipped_rows))
		self.assertEqual(len(new_schedule.repayment_schedule), len(old_schedule.repayment_schedule) + 3)
		self.assertEqual(getdate(new_schedule.repayment_schedule[-1].payment_date), getdate("2027-06-07"))
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)

	def test_installment_skip_keeping_the_tenure(self):
		loan = frappe.get_doc("Loan", self.loan)
		old_schedule = get_active_schedule(loan.name)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07", "2027-03-07"],
			new_repayment_method="Repay Over Number of Periods",
		)
		loan_restructure.status = "Approved"
		loan_restructure.save()

		# The EMI goes up. The last installment is skipped, so the loan ends on the one before it
		new_schedule = get_active_schedule(loan.name)
		rows = new_schedule.repayment_schedule
		self.assertGreater(new_schedule.monthly_repayment_amount, old_schedule.monthly_repayment_amount)
		self.assertEqual(getdate(rows[-1].payment_date), getdate("2027-02-07"))
		self.assertEqual(flt(rows[-1].balance_loan_amount, 2), 0)
		self.assertEqual(rows[-1].demand_generated, 0)
		self.assertTrue(all(getdate(row.payment_date) <= getdate("2027-02-07") for row in rows))

		# A later skip remembers the skipped date at the end of the term, so it is not demanded
		skip_installments(loan.name, '["2026-12-07"]', restructure_date="2026-10-21")

		schedule = get_active_schedule(loan.name)
		last_row = schedule.repayment_schedule[-1]
		self.assertEqual(get_row(schedule, "2026-11-07").total_payment, 0)
		self.assertEqual(get_row(schedule, "2026-12-07").total_payment, 0)
		self.assertFalse(
			any(getdate(row.payment_date) == getdate("2027-03-07") and row.total_payment for row in schedule.repayment_schedule)
		)
		self.assertEqual(flt(last_row.balance_loan_amount, 2), 0)
		# Same EMI is kept, so the loan runs longer instead of the last payment growing
		self.assertTrue(getdate(last_row.payment_date) > getdate("2027-03-07"))
		self.assertEqual(get_row(schedule, "2027-02-07").total_payment, schedule.monthly_repayment_amount)

	def test_later_skip_keeps_earlier_skip_and_cancelling_restores_the_loan(self):
		loan = frappe.get_doc("Loan", self.loan)
		old_schedule = get_active_schedule(loan.name)
		old_terms = frappe.db.get_value("Loan", loan.name, ["monthly_repayment_amount", "repayment_periods"])

		first = frappe.get_doc(
			"Loan Restructure", skip_installments(loan.name, '["2027-01-07"]', restructure_date="2026-10-20")
		)

		# The Loan shows the new terms
		first_terms = frappe.db.get_value("Loan", loan.name, ["monthly_repayment_amount", "repayment_periods"])
		self.assertEqual(first_terms[0], get_active_schedule(loan.name).monthly_repayment_amount)
		self.assertEqual(first_terms[1], old_terms[1] + 1)

		second = frappe.get_doc(
			"Loan Restructure", skip_installments(loan.name, '["2026-12-07"]', restructure_date="2026-10-21")
		)
		new_schedule = get_active_schedule(loan.name)

		# The schedule still starts on the loan's own repayment start date after two skips
		self.assertEqual(new_schedule.repayment_start_date, getdate("2026-10-07"))

		# Both skips are in force, and a period was added at the end for each
		skipped_rows = [row for row in new_schedule.repayment_schedule if not row.total_payment]
		self.assertEqual(
			[getdate(row.payment_date) for row in skipped_rows], [getdate("2026-12-07"), getdate("2027-01-07")]
		)
		self.assertTrue(all(row.demand_generated for row in skipped_rows))
		self.assertEqual(getdate(new_schedule.repayment_schedule[-1].payment_date), getdate("2027-05-07"))
		self.assertEqual(flt(new_schedule.repayment_schedule[-1].balance_loan_amount, 2), 0)

		# The older skip cannot be cancelled before the later one
		self.assertRaises(frappe.ValidationError, first.cancel)

		second.cancel()
		self.assertEqual(
			frappe.db.get_value("Loan", loan.name, ["monthly_repayment_amount", "repayment_periods"]), first_terms
		)

		first.reload()
		first.cancel()

		restored_schedule = get_active_schedule(loan.name)
		self.assertEqual(restored_schedule.name, old_schedule.name)
		self.assertEqual(restored_schedule.repayment_schedule[2].demand_generated, 0)
		self.assertEqual(
			frappe.db.get_value("Loan", loan.name, ["monthly_repayment_amount", "repayment_periods"]), old_terms
		)

	def test_rejected_installment_skip_keeps_the_schedule(self):
		loan = frappe.get_doc("Loan", self.loan)
		old_schedule = get_active_schedule(loan.name)

		open_installments = get_upcoming_installments(loan.name)
		self.assertEqual(getdate(open_installments[0]["payment_date"]), getdate("2026-11-07"))

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(
				loan.name, '["2026-11-07"]', reason="Employee request", approve=0, restructure_date="2026-10-20"
			),
		)
		self.assertEqual((restructure.restructure_type, restructure.status), ("Installment Skip", "Initiated"))
		self.assertEqual(restructure.reason_for_restructure, "Employee request")

		restructure.status = "Rejected"
		restructure.save()

		self.assertEqual(get_active_schedule(loan.name).name, old_schedule.name)

		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-10")
		self.assertIn(getdate("2026-11-07"), get_demand_dates(loan.name))

		# A new skip is allowed after a rejection
		create_repayment_entry(
			loan.name, "2026-11-10", calculate_amounts(loan.name, "2026-11-10")["payable_amount"]
		).submit()
		restructure = frappe.get_doc(
			"Loan Restructure", skip_installments(loan.name, '["2026-12-07"]', restructure_date="2026-11-12")
		)
		self.assertEqual(restructure.status, "Approved")
		self.assertEqual(get_row(get_active_schedule(loan.name), "2026-12-07").demand_generated, 1)

	def test_invalid_and_duplicate_installment_skips(self):
		loan = frappe.get_doc("Loan", self.loan)

		invalid_requests = [
			# not a schedule date
			("2026-10-20", ["2026-11-08"], None),
			# installment with demand already generated
			("2026-10-20", ["2026-10-07"], None),
			# same installment twice
			("2026-10-20", ["2026-11-07", "2026-11-07"], None),
			# nothing selected
			("2026-10-20", [], None),
			# installment is before the restructure date
			("2026-11-10", ["2026-11-07"], None),
			# no installment left to repay
			(
				"2026-10-20",
				["2026-11-07", "2026-12-07", "2027-01-07", "2027-02-07", "2027-03-07"],
				"Repay Over Number of Periods",
			),
		]

		for restructure_date, skipped_dates, new_repayment_method in invalid_requests:
			with self.assertRaises(frappe.ValidationError):
				create_loan_restructure(
					loan=loan.name,
					restructure_date=restructure_date,
					restructure_type="Installment Skip",
					skipped_dates=skipped_dates,
					new_repayment_method=new_repayment_method,
				)

		loan_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-20",
			restructure_type="Installment Skip",
			skipped_dates=["2026-11-07"],
		)

		# Second skip while the first is pending
		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-10-21",
				restructure_type="Installment Skip",
				skipped_dates=["2026-12-07"],
			)

		loan_restructure.status = "Approved"
		loan_restructure.save()

		# The same installment cannot be skipped twice
		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-10-21",
				restructure_type="Installment Skip",
				skipped_dates=["2026-11-07"],
			)

		# Another installment can be skipped once the first is done, and the first stays skipped
		second_restructure = create_loan_restructure(
			loan=loan.name,
			restructure_date="2026-10-21",
			restructure_type="Installment Skip",
			skipped_dates=["2026-12-07"],
		)
		second_restructure.status = "Approved"
		second_restructure.save()

		skipped_dates = [
			getdate(row.payment_date) for row in get_active_schedule(loan.name).repayment_schedule if not row.total_payment
		]
		self.assertEqual(skipped_dates, [getdate("2026-11-07"), getdate("2026-12-07")])

		# A loan that is not fully disbursed cannot skip
		frappe.db.set_value("Loan", loan.name, "status", "Partially Disbursed")
		self.assertRaises(
			frappe.ValidationError, skip_installments, loan.name, '["2027-01-07"]', restructure_date="2026-10-22"
		)

	def test_installment_skip_starts_after_last_accrual(self):
		loan = frappe.get_doc("Loan", self.loan)

		# Interest is already accrued till Nov 8, e.g. by a payroll run for a later period
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")
		create_repayment_entry(
			loan.name, "2026-11-07", calculate_amounts(loan.name, "2026-11-07")["payable_amount"]
		).submit()
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-11-08")

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(loan.name, '["2026-12-07"]', restructure_date="2026-10-20"),
		)

		self.assertEqual(restructure.status, "Approved")
		self.assertGreaterEqual(getdate(restructure.restructure_date), getdate("2026-11-08"))

	def test_installment_skip_does_not_demand_interest_twice(self):
		loan = frappe.get_doc("Loan", self.loan)

		# Interest is accrued till Nov 6 and the Nov 7 installment is demanded and paid
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-11-06")
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")
		create_repayment_entry(
			loan.name, "2026-11-07", calculate_amounts(loan.name, "2026-11-07")["payable_amount"]
		).submit()

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(loan.name, '["2026-12-07"]', restructure_date="2026-10-20"),
		)
		new_schedule = get_active_schedule(loan.name)

		# Starts at the demanded installment, so nothing before it is added again
		self.assertEqual(getdate(restructure.restructure_date), getdate("2026-11-07"))
		self.assertEqual(restructure.unaccrued_interest, 0)

		# Interest of Nov 7 to Jan 7 is demanded once: skipped Dec 7 and the Jan 7 installment
		self.assertAlmostEqual(
			next_row(new_schedule, "2026-12-07").interest_amount,
			restructure.new_loan_amount * 12 * 61 / 36500,
			delta=0.5,
		)

		# Entered directly, an earlier date is refused
		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-11-06",
				restructure_type="Installment Skip",
				skipped_dates=["2027-01-07"],
			)

	def test_installment_skip_is_not_allowed_with_overdue(self):
		loan = frappe.get_doc("Loan", self.loan)
		old_schedule = get_active_schedule(loan.name)

		# Without a skip, the schedule and the demand are as they were
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")
		self.assertEqual(get_active_schedule(loan.name).name, old_schedule.name)
		self.assertEqual(
			calculate_amounts(loan.name, "2026-11-07")["payable_amount"],
			old_schedule.repayment_schedule[2].total_payment,
		)

		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-11-10",
				restructure_type="Installment Skip",
				skipped_dates=["2026-12-07"],
			)

	def test_installment_skip_generates_demand_for_due_installments_first(self):
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			120000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2026-10-25",
			posting_date="2026-09-15",
			rate_of_interest=12,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2026-09-15", repayment_start_date="2026-10-25"
		)

		# No demand is generated yet, so the broken period interest row of 25 Sep is still open
		self.assertEqual(get_demand_dates(loan.name), [])
		offered = [getdate(row["payment_date"]) for row in get_upcoming_installments(loan.name)]
		self.assertTrue(offered)
		self.assertGreaterEqual(min(offered), getdate("2026-10-25"))

		restructure = frappe.get_doc(
			"Loan Restructure",
			skip_installments(loan.name, '["2026-11-25"]', restructure_date="2026-10-23"),
		)

		self.assertEqual(restructure.status, "Approved")
		self.assertIn(getdate("2026-09-25"), get_demand_dates(loan.name))
		new_schedule = get_active_schedule(loan.name)
		self.assertEqual(get_row(new_schedule, "2026-09-25").demand_generated, 1)
		self.assertEqual(getdate(next_row(new_schedule, "2026-09-25").payment_date), getdate("2026-10-25"))

		# Entered directly, with an installment still without demand before the date, it is refused
		with self.assertRaises(frappe.ValidationError):
			create_loan_restructure(
				loan=loan.name,
				restructure_date="2026-11-30",
				restructure_type="Installment Skip",
				skipped_dates=["2026-12-25"],
			)


class TestInstallmentSkipRepost(InstallmentSkipTestCase):
	"""Loan Repayment Repost keeps skipped installments skipped and allocates the payments again"""

	def test_repost_with_installment_skips(self):
		loan = frappe.get_doc("Loan", self.loan)

		skip_installments(loan.name, '["2026-11-07"]', restructure_date="2026-10-20")

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-12-06")
		process_daily_loan_demands(loan=loan.name, posting_date="2026-12-07")
		create_repayment_entry(
			loan.name, "2026-12-07", calculate_amounts(loan.name, "2026-12-07")["payable_amount"]
		).submit()

		# Repost after the skipped installment
		repost(loan.name, "2026-10-10")

		skipped_row = get_row(get_active_schedule(loan.name), "2026-11-07")
		self.assertEqual(skipped_row.demand_generated, 1)

		# No demand for the skipped installment, and the payment of the next one is allocated again
		demand_dates, outstanding = get_emi_demands(loan.name)
		self.assertNotIn(getdate("2026-11-07"), demand_dates)
		self.assertEqual(outstanding, 0)

		# The skipped installment is not offered for a second skip
		open_dates = [getdate(row["payment_date"]) for row in get_upcoming_installments(loan.name)]
		self.assertNotIn(getdate("2026-11-07"), open_dates)
		self.assertNotIn(getdate("2026-12-07"), open_dates)

		# Repost before the skip: the installment demanded before the skip is demanded and allocated again
		repost(loan.name, "2026-10-07")

		demand_dates, outstanding = get_emi_demands(loan.name)
		self.assertIn(getdate("2026-10-07"), demand_dates)
		self.assertIn(getdate("2026-12-07"), demand_dates)
		self.assertNotIn(getdate("2026-11-07"), demand_dates)
		self.assertEqual(outstanding, 0)

		# A second skip, then a repost between the two: paid installments get demand and allocation again,
		# the skipped ones get no demand
		skip_installments(loan.name, '["2027-02-07"]', restructure_date="2026-12-08")
		repost(loan.name, "2026-11-15")

		demand_dates, outstanding = get_emi_demands(loan.name)
		self.assertIn(getdate("2026-10-07"), demand_dates)
		self.assertIn(getdate("2026-12-07"), demand_dates)
		self.assertNotIn(getdate("2026-11-07"), demand_dates)
		self.assertNotIn(getdate("2027-02-07"), demand_dates)
		self.assertEqual(outstanding, 0)


def repost(loan, repost_date):
	frappe.get_doc(
		{
			"doctype": "Loan Repayment Repost",
			"loan": loan,
			"repost_date": repost_date,
			"cancel_future_emi_demands": 1,
			"cancel_future_accruals_and_demands": 1,
		}
	).submit()


def get_emi_demands(loan):
	demands = frappe.get_all(
		"Loan Demand",
		{"loan": loan, "docstatus": 1, "demand_type": "EMI"},
		["demand_date", "outstanding_amount"],
	)
	return [getdate(d.demand_date) for d in demands], sum(flt(d.outstanding_amount) for d in demands)


def make_request(loan, dates, method="Repay Fixed Amount per Period"):
	request = frappe.new_doc("Loan Installment Skip Request")
	request.loan = loan
	request.new_repayment_method = method
	request.reason = "Employee request"
	for date in dates:
		request.append("skipped_installments", {"payment_date": getdate(date)})

	request.insert()
	return request


def approve(request):
	request.status = "Approved"
	request.submit()


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)

	frappe.get_doc("User", email).add_roles(*roles)
	return email


def get_active_schedule(loan):
	return frappe.get_doc("Loan Repayment Schedule", {"loan": loan, "docstatus": 1, "status": "Active"})


def get_row(schedule, date):
	return next(row for row in schedule.repayment_schedule if getdate(row.payment_date) == getdate(date))


def next_row(schedule, date):
	rows = schedule.repayment_schedule
	return rows[rows.index(get_row(schedule, date)) + 1]


def get_demand_dates(loan):
	return [
		getdate(date) for date in frappe.get_all("Loan Demand", {"loan": loan, "docstatus": 1}, pluck="demand_date")
	]


def make_loan_with_first_emi_paid(method="Repay Over Number of Periods"):
	set_loan_accrual_frequency(loan_accrual_frequency="Daily")

	loan = create_loan(
		"_Test Customer 1",
		"Term Loan Product 4",
		120000,
		method,
		6,
		repayment_start_date="2026-10-07",
		posting_date="2026-09-01",
		rate_of_interest=12,
		applicant_type="Customer",
	)
	loan.submit()

	make_loan_disbursement_entry(
		loan.name, loan.loan_amount, disbursement_date="2026-09-01", repayment_start_date="2026-10-07"
	)
	process_loan_interest_accrual_for_loans(
		posting_date="2026-10-06", loan=loan.name, company="_Test Company"
	)
	process_daily_loan_demands(loan=loan.name, posting_date="2026-10-07")
	create_repayment_entry(
		loan.name, "2026-10-07", calculate_amounts(loan.name, "2026-10-07")["payable_amount"]
	).submit()
	process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-10-19")

	return loan
