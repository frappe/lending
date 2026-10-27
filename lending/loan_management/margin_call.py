import frappe
from frappe.utils import cint, date_diff, get_datetime, nowdate

import erpnext

from lending.loan_management.collections import get_applicant_email
from lending.loan_management.utils import add_working_days

PROCESSED_STATUSES = ("Pending", "Notified", "Sale Triggered")
REMINDER_DAYS = 2


def process_open_shortfalls():
	if not frappe.db.get_single_value("Lending Settings", "enable_margin_call"):
		return
	cure_days = cint(frappe.db.get_single_value("Lending Settings", "margin_cure_days"))

	shortfalls = frappe.get_all(
		"Loan Security Shortfall", filters={"status": ("in", PROCESSED_STATUSES)}, pluck="name"
	)
	for shortfall in shortfalls:
		frappe.db.savepoint("margin_call")
		try:
			MarginCall(shortfall, cure_days).process()
		except Exception:
			frappe.db.rollback(save_point="margin_call")
			frappe.log_error(
				title=f"Margin call failed for {shortfall}",
				reference_doctype="Loan Security Shortfall",
				reference_name=shortfall,
			)


class MarginCall:
	def __init__(self, shortfall, cure_days):
		# A run queued by a Price Update can overlap the daily one; the row lock makes the second wait
		self.doc = frappe.get_doc("Loan Security Shortfall", shortfall, for_update=True)
		self.cure_days = cure_days

	def process(self):
		# A price feed gap is not a price fall: wait for the prices before telling the borrower
		if self.doc.status not in PROCESSED_STATUSES or self.doc.missing_price:
			return

		if not self.doc.notified_on and not self.notify():
			return

		days_left = date_diff(self.doc.cure_by, nowdate()) if self.doc.cure_by else None
		if self.doc.status == "Notified" and days_left < 0:
			self.escalate()
		elif self.doc.status == "Notified" and days_left <= REMINDER_DAYS and not self.doc.reminded_on:
			self.remind()
		elif self.doc.status == "Sale Triggered":
			self.draft_sale()

	def remind(self):
		self.doc.db_set("reminded_on", get_datetime())
		# Sends the standard "Margin Call Reminder" Notification
		self.doc.run_method("remind_margin_call")

	def notify(self):
		self.doc.applicant_email = get_applicant_email(self.doc.applicant_type, self.doc.applicant)
		if not self.doc.applicant_email:
			if not self.doc.email_missing:
				self.doc.email_missing = 1
				# Saved, not db_set, so that the Margin Call Email Missing alert fires
				self.doc.save(ignore_permissions=True)
			return False

		self.doc.email_missing = 0
		self.doc.notified_on = get_datetime()
		self.doc.cure_by = add_working_days(nowdate(), self.cure_days, self.get_holiday_list())
		if self.doc.status == "Pending":
			self.doc.status = "Notified"
		self.doc.save(ignore_permissions=True)
		# Sends the standard "Margin Call Notice" Notification
		self.doc.run_method("notify_margin_call")
		return True

	def escalate(self):
		self.doc.db_set("status", "Escalated")
		self.draft_sale()

	def draft_sale(self):
		if not self.doc.loan or frappe.db.exists(
			"Loan Security Sale", {"loan_security_shortfall": self.doc.name, "docstatus": ("<", 2)}
		):
			return

		sale = frappe.new_doc("Loan Security Sale")
		sale.loan = self.doc.loan
		sale.loan_security_shortfall = self.doc.name
		sale.reason = "Margin Call Not Cured"
		sale.posting_date = nowdate()
		sale.prefill_items()
		# Without current prices nothing can be prefilled, and staff still need the draft
		sale.flags.ignore_mandatory = True
		sale.insert(ignore_permissions=True)

	def get_holiday_list(self):
		company = (
			frappe.db.get_value("Loan", self.doc.loan, "company")
			if self.doc.loan
			else erpnext.get_default_company()
		)
		return frappe.get_cached_value("Company", company, "default_holiday_list")
