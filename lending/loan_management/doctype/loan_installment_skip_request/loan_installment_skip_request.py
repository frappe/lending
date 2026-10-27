# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_restructure.installment_skip import (
	InstallmentSkip,
	get_skip_date,
	skip_installments,
	validate_loan_access,
)

APPROVER_ROLES = ("Loan Manager", "System Manager")


class LoanInstallmentSkipRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_skipped_installment.loan_skipped_installment import (
			LoanSkippedInstallment,
		)

		amended_from: DF.Link | None
		applicant: DF.Data | None
		applicant_name: DF.Data | None
		applicant_type: DF.Data | None
		approver: DF.Link | None
		approver_name: DF.Data | None
		approver_remarks: DF.SmallText | None
		company: DF.Link | None
		loan: DF.Link
		loan_product: DF.Link | None
		loan_restructure: DF.Link | None
		new_repayment_method: DF.Literal["Repay Fixed Amount per Period", "Repay Over Number of Periods"]
		reason: DF.SmallText | None
		skipped_installments: DF.Table[LoanSkippedInstallment]
		status: DF.Literal["Open", "Approved", "Rejected", "Cancelled"]
	# end: auto-generated types

	def validate(self):
		# The approver decides on a request without needing access to the loan itself
		if self.is_new():
			validate_loan_access(self.loan)

		self.set_status_for_new_request()
		self.validate_installments_can_be_skipped()
		self.validate_no_other_request_for_installments()
		self.validate_approver_for_decision()

	def after_insert(self):
		if self.needs_approval():
			self.share_with_approver()
		else:
			self.approve_automatically()

	def before_submit(self):
		if self.status not in ("Approved", "Rejected"):
			frappe.throw(_("Only a request with status Approved or Rejected can be submitted"))

		self.validate_approver_for_decision(on_submit=True)

	def on_submit(self):
		if self.status == "Approved":
			self.db_set("loan_restructure", self.make_loan_restructure())

	def on_cancel(self):
		self.db_set("status", "Cancelled")

		if self.loan_restructure and frappe.db.get_value("Loan Restructure", self.loan_restructure, "docstatus") == 1:
			with system_user():
				frappe.get_doc("Loan Restructure", self.loan_restructure).cancel()

	def needs_approval(self):
		return frappe.db.get_value("Loan Product", self.loan_product, "installment_skip_needs_approval")

	def set_status_for_new_request(self):
		# A request starts as Open. Only the auto approval below may start it as Approved.
		if self.is_new() and not self.flags.auto_approved:
			self.status = "Open"

	def validate_installments_can_be_skipped(self):
		# Once decided, the Loan Restructure checks everything again on approval
		if self.docstatus or self.status != "Open":
			return

		skip = InstallmentSkip(
			frappe._dict(
				loan=self.loan,
				loan_disbursement=None,
				restructure_date=get_skip_date(self.loan),
				skipped_installments=self.skipped_installments,
				total_overdue_amount=self.get_overdue_amount(),
			)
		)
		skip.validate_loan()
		skip.validate_no_overdue()
		skip.validate_skipped_installments()

	def get_overdue_amount(self):
		amounts = calculate_amounts(self.loan, frappe.utils.nowdate())
		return flt(amounts.get("payable_amount"))

	def validate_no_other_request_for_installments(self):
		dates = [getdate(row.payment_date) for row in self.skipped_installments]
		if not dates:
			return

		Request = frappe.qb.DocType("Loan Installment Skip Request")
		Skipped = frappe.qb.DocType("Loan Skipped Installment")

		query = (
			frappe.qb.from_(Skipped)
			.join(Request)
			.on(Skipped.parent == Request.name)
			.select(Request.name, Skipped.payment_date)
			.where(
				(Request.loan == self.loan)
				& (Request.docstatus < 2)
				& (Request.status.isin(["Open", "Approved"]))
				& (Request.name != (self.name or ""))
				& (Skipped.payment_date.isin(dates))
			)
		)

		for name, date in query.run():
			frappe.throw(
				_("Installment of {0} is already in the request {1}").format(getdate(date), frappe.bold(name))
			)

	def validate_approver_for_decision(self, on_submit=False):
		if self.flags.auto_approved or self.status not in ("Approved", "Rejected"):
			return

		if not self.can_decide():
			frappe.throw(_("Only {0} or a Loan Manager can approve or reject this request").format(
				frappe.bold(self.approver_name or self.approver or _("a Loan Manager"))
			))

	def can_decide(self):
		roles = frappe.get_roles()
		return (
			frappe.session.user == self.approver
			or any(role in roles for role in APPROVER_ROLES)
		)

	def share_with_approver(self):
		if not self.approver:
			return

		frappe.share.add_docshare(
			self.doctype,
			self.name,
			self.approver,
			read=1,
			write=1,
			submit=1,
			notify=1,
			flags={"ignore_share_permission": True},
		)

	def approve_automatically(self):
		# Submit a fresh copy. Submitting self here would run on_submit twice, as insert still has its own post save steps
		request = frappe.get_doc(self.doctype, self.name)
		request.flags.auto_approved = True
		request.flags.ignore_permissions = True
		request.status = "Approved"
		request.submit()

		self.reload()

	def make_loan_restructure(self):
		# The approver may have no access to schedules or demands. The request keeps who approved.
		with system_user():
			return skip_installments(
				self.loan,
				frappe.as_json([str(row.payment_date) for row in self.skipped_installments]),
				new_repayment_method=self.new_repayment_method,
				reason=self.reason,
				request=self.name,
			)


@contextmanager
def system_user():
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		yield
	finally:
		frappe.set_user(user)
