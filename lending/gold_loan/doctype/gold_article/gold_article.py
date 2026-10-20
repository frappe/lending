# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

FIXED_ONCE_PLEDGED = ("applicant_type", "applicant", "metal", "article_kind")


class GoldArticle(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		applicant: DF.DynamicLink
		applicant_name: DF.Data | None
		applicant_type: DF.Literal["Customer", "Employee"]
		article_kind: DF.Literal["Ornament", "Coin"]
		assayed_on: DF.Date | None
		current_assignment: DF.Link | None
		deduction_weight: DF.Float
		defects: DF.SmallText | None
		description: DF.Data
		fineness: DF.Int
		gross_weight: DF.Float
		image: DF.AttachImage
		metal: DF.Literal["Gold", "Silver"]
		net_weight: DF.Float
		packet_number: DF.Data | None
		pieces: DF.Int
		status: DF.Literal["Available", "Pledged", "Released", "Sold"]
		title: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self.validate_fixed_fields()
		self.set_applicant_name()
		self.title = self.description

	def validate_fixed_fields(self):
		if self.is_new() or self.status == "Available":
			return

		for fieldname in FIXED_ONCE_PLEDGED:
			if self.has_value_changed(fieldname):
				frappe.throw(
					_("{0} cannot change once the article has been pledged").format(
						self.meta.get_label(fieldname)
					)
				)

	def set_applicant_name(self):
		if self.applicant_type == "Customer":
			self.applicant_name = frappe.db.get_value("Customer", self.applicant, "customer_name")
		elif self.applicant_type == "Employee":
			self.applicant_name = frappe.db.get_value("Employee", self.applicant, "employee_name")
