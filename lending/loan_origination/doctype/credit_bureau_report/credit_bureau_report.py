# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime


class CreditBureauReport(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		applicant: DF.DynamicLink | None
		applicant_type: DF.Literal["Customer", "Employee"]
		bureau: DF.Literal["CIBIL", "Experian", "Equifax", "CRIF", "Manual"]
		pan: DF.Data | None
		raw_payload: DF.LongText | None
		report_date: DF.Datetime
		score: DF.Int
		total_emi: DF.Currency
	# end: auto-generated types

	def validate(self):
		self.validate_report_date()

	def validate_report_date(self):
		if self.report_date and get_datetime(self.report_date) > now_datetime():
			frappe.throw(_("Report Date cannot be in the future."))
