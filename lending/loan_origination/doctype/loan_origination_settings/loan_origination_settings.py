# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document

from lending.loan_origination.doctype.loan_lead.loan_lead import (
	OTP_MEDIUM_FIELD_MAP,
	TELEPHONY_APP,
)

fields_that_can_have_unique_constraints = ["mobile_no", "email_id"]


class LoanOriginationSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		employee_loans: DF.Check
		otp_for_email: DF.Check
		otp_for_sms: DF.Check
		otp_verification_mandatory: DF.Check
		unique_customer: DF.Check
	# end: auto-generated types

	def validate(self):
		self.validate_otp_mediums()

	def validate_otp_mediums(self):
		enabled = [
			fields
			for fields in OTP_MEDIUM_FIELD_MAP.values()
			if self.get(fields["enable_field"]) and self.has_value_changed(fields["enable_field"])
		]
		if not enabled:
			return

		if TELEPHONY_APP not in frappe.get_installed_apps():
			frappe.throw(
				_("Please install the Telephony app to send OTPs, or turn OTP for Email and SMS off.")
			)

		otp_settings = frappe.get_cached_doc("TP OTP Settings")
		for fields in enabled:
			if not otp_settings.get(fields["telephony_field"]):
				frappe.throw(
					_("Please enable {0} in TP OTP Settings to use {1}.").format(
						_(fields["telephony_label"]),
						_(self.meta.get_label(fields["enable_field"])),
					)
				)

	def before_save(self):
		if self.unique_customer:
			add_unique_constraints()
		else:
			remove_unique_constraints()


def add_unique_constraints():
	fields_with_unique_constraints = get_fields_with_unique_constraints()

	for field in set(fields_that_can_have_unique_constraints).difference(
		set(fields_with_unique_constraints)
	):
		try:
			frappe.db.add_unique("Customer", field)

		except Exception:
			remove_unique_constraints()


def remove_unique_constraints():
	fields_with_unique_constraints = get_fields_with_unique_constraints()
	for field in fields_with_unique_constraints:
		frappe.db.sql_ddl(f"""alter table tabCustomer drop index unique_{field}""")


def get_fields_with_unique_constraints():
	statistics = frappe.qb.Table("statistics", schema="information_schema")
	fields_with_unique_constraints = (
		frappe.qb.from_(statistics)
		.select(statistics.column_name)
		.where(statistics.table_name == "tabCustomer")
		.where(statistics.column_name.isin(fields_that_can_have_unique_constraints))
		.where(statistics.non_unique == 0)
		.run()
	)
	fields_with_unique_constraints = [i[0] for i in fields_with_unique_constraints]

	return fields_with_unique_constraints
