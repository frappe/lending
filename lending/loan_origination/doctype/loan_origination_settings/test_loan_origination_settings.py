# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from lending.loan_origination.doctype.loan_origination_settings.loan_origination_settings import (
	TELEPHONY_APP,
)
from lending.tests.utils import LendingTestSuite


class TestLoanOriginationSettings(LendingTestSuite):
	def test_otp_medium_cannot_be_enabled_without_its_telephony_channel(self):
		if TELEPHONY_APP not in frappe.get_installed_apps():
			self.skipTest("requires the Telephony app to be installed")

		frappe.db.set_single_value("TP OTP Settings", "enable_email_otp", 0)
		frappe.clear_cache(doctype="TP OTP Settings")
		self.addCleanup(frappe.clear_cache, doctype="TP OTP Settings")

		frappe.db.set_single_value("Loan Origination Settings", "otp_for_email", 0)
		frappe.clear_cache(doctype="Loan Origination Settings")
		self.addCleanup(frappe.clear_cache, doctype="Loan Origination Settings")

		settings = frappe.get_doc("Loan Origination Settings")
		settings.otp_for_email = 1

		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_settings_stay_saveable_when_a_telephony_channel_is_turned_off(self):
		if TELEPHONY_APP not in frappe.get_installed_apps():
			self.skipTest("requires the Telephony app to be installed")

		frappe.db.set_single_value("TP OTP Settings", "enable_email_otp", 0)
		frappe.db.set_single_value("Loan Origination Settings", "otp_for_email", 1)
		frappe.clear_cache(doctype="TP OTP Settings")
		frappe.clear_cache(doctype="Loan Origination Settings")
		self.addCleanup(frappe.clear_cache, doctype="TP OTP Settings")
		self.addCleanup(frappe.clear_cache, doctype="Loan Origination Settings")

		settings = frappe.get_doc("Loan Origination Settings")
		settings.load_doc_before_save()

		settings.employee_loans = not settings.employee_loans
		settings.validate_otp_mediums()

		settings.otp_for_email = 0
		settings.validate_otp_mediums()
