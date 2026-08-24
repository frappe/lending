# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document

fields_that_can_have_unique_constraints = ["mobile_no", "email_id"]

TELEPHONY_APP = "telephony"

# Maps each medium to the TP OTP Settings switch it is delivered through.
OTP_MEDIUM_TELEPHONY_SETTING = {
	"otp_for_email": ("enable_email_otp", "Email OTP"),
	"otp_for_sms": ("enabled", "SMS"),
}


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
		# Only mediums switched on by this save, so the document stays saveable later.
		enabled_mediums = [
			fieldname
			for fieldname in OTP_MEDIUM_TELEPHONY_SETTING
			if self.get(fieldname) and self.has_value_changed(fieldname)
		]
		if not enabled_mediums:
			return

		if TELEPHONY_APP not in frappe.get_installed_apps():
			frappe.throw(
				_("Please install the Telephony app to send OTPs, or turn OTP for Email and SMS off.")
			)

		otp_settings = frappe.get_cached_doc("TP OTP Settings")
		for fieldname in enabled_mediums:
			telephony_field, label = OTP_MEDIUM_TELEPHONY_SETTING[fieldname]
			if not otp_settings.get(telephony_field):
				frappe.throw(
					_("Please enable {0} in TP OTP Settings to use {1}.").format(
						_(label), _(self.meta.get_label(fieldname))
					)
				)

	def before_save(self):
		if self.unique_customer:
			add_unique_constraints()
		else:
			remove_unique_constraints()


def add_unique_constraints():
	fields_with_unique_constraints = get_fields_with_unique_constraints()

	# for field in fields_with_unique_constraints
	for field in set(fields_that_can_have_unique_constraints).difference(
		set(fields_with_unique_constraints)
	):
		try:
			frappe.db.add_unique("Customer", field)

		except Exception:
			# remove any added constraints
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
