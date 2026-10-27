# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import getdate

from lending.loan_management.doctype.loan_restructure.test_loan_restructure import (
	get_active_schedule,
	get_row,
	make_loan_with_first_emi_paid,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import init_customers, init_loan_products
from lending.tests.utils import LendingTestSuite


class TestLoanInstallmentSkipRequest(LendingTestSuite):
	@classmethod
	def make_class_data(cls):
		init_loan_products()
		init_customers()

	def test_request_stays_open_until_it_is_approved(self):
		loan = make_loan_with_first_emi_paid()
		request = make_request(loan.name, ["2026-11-07"])

		self.assertEqual((request.docstatus, request.status), (0, "Open"))
		self.assertFalse(request.loan_restructure)
		# The schedule is not touched before approval
		self.assertEqual(get_row(get_active_schedule(loan.name), "2026-11-07").demand_generated, 0)

		approve(request)

		request.reload()
		self.assertEqual((request.docstatus, request.status), (1, "Approved"))

		restructure = frappe.get_doc("Loan Restructure", request.loan_restructure)
		self.assertEqual((restructure.restructure_type, restructure.status), ("Installment Skip", "Approved"))
		self.assertEqual(restructure.loan_installment_skip_request, request.name)

		skipped_row = get_row(get_active_schedule(loan.name), "2026-11-07")
		self.assertEqual((skipped_row.total_payment, skipped_row.demand_generated), (0, 1))

	def test_approver_is_taken_from_the_loan(self):
		loan = make_loan_with_first_emi_paid()
		approver = make_user("skip.approver@example.com", ["Employee"])
		frappe.db.set_value("Loan", loan.name, "installment_skip_approver", approver)

		request = make_request(loan.name, ["2026-11-07"])

		self.assertEqual(request.approver, approver)

	def test_rejected_request_keeps_the_schedule(self):
		loan = make_loan_with_first_emi_paid()
		request = make_request(loan.name, ["2026-11-07"])

		request.status = "Rejected"
		request.approver_remarks = "Not allowed this month"
		request.submit()

		request.reload()
		self.assertEqual((request.docstatus, request.status), (1, "Rejected"))
		self.assertFalse(request.loan_restructure)
		self.assertEqual(get_row(get_active_schedule(loan.name), "2026-11-07").total_payment > 0, True)

	def test_request_is_approved_at_once_when_approval_is_not_needed(self):
		loan = make_loan_with_first_emi_paid()
		frappe.db.set_value("Loan Product", loan.loan_product, "installment_skip_needs_approval", 0)

		request = make_request(loan.name, ["2026-11-07"])

		request.reload()
		self.assertEqual((request.docstatus, request.status), (1, "Approved"))
		self.assertEqual(frappe.db.get_value("Loan Restructure", request.loan_restructure, "status"), "Approved")

	def test_only_the_approver_or_a_loan_manager_can_decide(self):
		loan = make_loan_with_first_emi_paid()
		approver = make_user("skip.approver@example.com", ["Employee"])
		other_user = make_user("skip.other@example.com", ["Employee"])
		frappe.db.set_value("Loan", loan.name, "installment_skip_approver", approver)
		request = make_request(loan.name, ["2026-11-07"])

		request.status = "Approved"
		frappe.set_user(other_user)
		try:
			self.assertRaises((frappe.PermissionError, frappe.ValidationError), request.submit)
		finally:
			frappe.set_user("Administrator")

		# The named approver has no lending role, the request is shared with them
		request = frappe.get_doc("Loan Installment Skip Request", request.name)
		request.status = "Approved"
		frappe.set_user(approver)
		try:
			request.submit()
		finally:
			frappe.set_user("Administrator")

		request.reload()
		self.assertEqual(request.status, "Approved")
		self.assertTrue(request.loan_restructure)

	def test_loan_manager_can_approve(self):
		loan = make_loan_with_first_emi_paid()
		request = make_request(loan.name, ["2026-11-07"])
		manager = make_user("skip.manager@example.com", ["Loan Manager"])

		request.status = "Approved"
		frappe.set_user(manager)
		try:
			request.submit()
		finally:
			frappe.set_user("Administrator")

		request.reload()
		self.assertTrue(request.loan_restructure)

	def test_same_installment_cannot_be_requested_twice(self):
		loan = make_loan_with_first_emi_paid()
		make_request(loan.name, ["2026-11-07"])

		self.assertRaises(frappe.ValidationError, make_request, loan.name, ["2026-11-07", "2026-12-07"])

		# A rejected request does not block a new one
		other = make_request(loan.name, ["2026-12-07"])
		other.status = "Rejected"
		other.submit()
		make_request(loan.name, ["2026-12-07"])

	def test_installment_with_demand_cannot_be_requested(self):
		loan = make_loan_with_first_emi_paid()
		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-11-07")
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")

		self.assertRaises(frappe.ValidationError, make_request, loan.name, ["2026-11-07"])

	def test_approval_fails_when_demand_is_generated_after_the_request(self):
		loan = make_loan_with_first_emi_paid()
		request = make_request(loan.name, ["2026-11-07"])

		process_loan_interest_accrual_for_loans(loan=loan.name, posting_date="2026-11-07")
		process_daily_loan_demands(loan=loan.name, posting_date="2026-11-07")

		# A failed request is rolled back, as it is when it comes from the browser
		frappe.db.savepoint("approval")
		self.assertRaises(frappe.ValidationError, approve, request)
		frappe.db.rollback(save_point="approval")

		request.reload()
		self.assertEqual((request.docstatus, request.status), (0, "Open"))
		self.assertFalse(request.loan_restructure)

	def test_cancelling_approved_request_cancels_the_loan_restructure(self):
		loan = make_loan_with_first_emi_paid()
		old_schedule = get_active_schedule(loan.name)
		request = make_request(loan.name, ["2026-11-07"])
		approve(request)
		request.reload()

		request.cancel()

		request.reload()
		self.assertEqual(request.status, "Cancelled")
		self.assertEqual(frappe.db.get_value("Loan Restructure", request.loan_restructure, "docstatus"), 2)
		self.assertEqual(get_active_schedule(loan.name).name, old_schedule.name)

	def test_user_without_access_to_the_loan_cannot_request(self):
		loan = make_loan_with_first_emi_paid()
		stranger = make_user("skip.stranger@example.com", ["Employee"])

		frappe.set_user(stranger)
		try:
			self.assertRaises(frappe.PermissionError, make_request, loan.name, ["2026-11-07"])
		finally:
			frappe.set_user("Administrator")

	def test_loan_that_cannot_skip_is_refused(self):
		loan = make_loan_with_first_emi_paid()
		frappe.db.set_value("Loan", loan.name, "status", "Partially Disbursed")

		self.assertRaises(frappe.ValidationError, make_request, loan.name, ["2026-11-07"])


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
