# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

RC_DOCUMENT_TYPE = "RC"
INVOICE_DOCUMENT_TYPE = "Tax Invoice"
OPEN_STATUSES = ("Pending", "Overdue")


class PostDisbursalDocument(Document):
	def validate(self):
		self.validate_status()

	def on_update(self):
		if self.status == "Verified" and self.has_value_changed("status"):
			self.update_vehicle()

	def validate_status(self):
		if self.status in ("Received", "Verified") and not self.file:
			frappe.throw(_("Attach the document before marking it {0}").format(self.status))

		if self.status in ("Received", "Verified") and not self.received_on:
			self.received_on = getdate(nowdate())

		if self.status in ("Verified", "Waived") and self.has_value_changed("status"):
			if "Loan Manager" not in frappe.get_roles() and frappe.session.user != "Administrator":
				frappe.throw(_("Only a Loan Manager can mark a document {0}").format(self.status))

		if self.status == "Verified":
			self.verified_by = self.verified_by or frappe.session.user
			if self.document_type == RC_DOCUMENT_TYPE and not self.registration_number:
				frappe.throw(_("Registration Number is required to verify the RC"))

		if self.status == "Waived" and not self.waiver_reason:
			frappe.throw(_("Waiver Reason is required"))

		if self.status == "Pending" and getdate(self.due_date) < getdate(nowdate()):
			self.status = "Overdue"

	def update_vehicle(self):
		vehicle = frappe.get_doc("Loan Vehicle", self.vehicle)

		if self.document_type == RC_DOCUMENT_TYPE:
			vehicle.registration_number = self.registration_number
			vehicle.registration_date = self.registration_date
			vehicle.rc_copy = self.file
			if self.hypothecation_endorsed and vehicle.hypothecation_status == "Not Endorsed":
				vehicle.hypothecation_status = "Endorsed"
				vehicle.hypothecation_endorsed_on = self.received_on
		elif self.document_type == INVOICE_DOCUMENT_TYPE:
			vehicle.invoice_copy = self.file

		vehicle.save(ignore_permissions=True)


def mark_overdue_documents():
	frappe.db.set_value(
		"Post Disbursal Document",
		{"status": "Pending", "due_date": ("<", nowdate())},
		"status",
		"Overdue",
	)
