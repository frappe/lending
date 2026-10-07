# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import getdate, today


class CollectionCase(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.collection_activity.collection_activity import (
			CollectionActivity,
		)
		from lending.loan_management.doctype.promise_to_pay.promise_to_pay import PromisetoPay

		activities: DF.Table[CollectionActivity]
		applicant: DF.DynamicLink | None
		applicant_email: DF.Data | None
		applicant_type: DF.Literal["", "Customer", "Employee"]
		assigned_agent: DF.Link | None
		branch: DF.Link | None
		bucket: DF.Data
		classification_code: DF.Link
		closed_on: DF.Date | None
		company: DF.Link
		days_past_due: DF.Int
		linked_restructure: DF.Link | None
		loan: DF.Link
		loan_product: DF.Link | None
		next_action_date: DF.Date | None
		opened_on: DF.Date
		outstanding_amount: DF.Currency
		promise_to_pay: DF.Table[PromisetoPay]
		resolution_reason: DF.SmallText | None
		status: DF.Literal[
			"Open", "In Progress", "Promise to Pay", "Broken PTP", "Hardship Requested", "Resolved", "Closed"
		]
	# end: auto-generated types

	def validate(self):
		self.reconcile_promise_to_pay()

	def reconcile_promise_to_pay(self):
		"""Mark an Open PTP as Broken once its promised date has passed unpaid. Runs
		regardless of status, since a promise can be added before anyone flips the
		case to "Promise to Pay"."""
		if self.status in ("Resolved", "Closed", "Hardship Requested"):
			return

		open_ptp_exists = False
		broken_now = False

		for ptp in self.promise_to_pay:
			if ptp.status != "Open":
				continue

			open_ptp_exists = True

			if getdate(ptp.promised_date) < getdate(today()) and not ptp.actual_paid_amount:
				ptp.status = "Broken"
				broken_now = True
				open_ptp_exists = False

		if broken_now:
			self.status = "Broken PTP"
		elif open_ptp_exists:
			self.status = "Promise to Pay"
