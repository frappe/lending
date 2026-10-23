from unittest.mock import patch

import frappe
from frappe.utils import add_days, nowdate

from erpnext.tests.utils import ERPNextTestSuite

from lending.loan_management.doctype.loan import loan as loan_module
from lending.tests.test_utils import (
	create_loan_accounts,
	create_loan_product,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	init_customers,
	init_loan_products,
	make_customer,
	set_loan_accrual_frequency,
	set_loan_settings_in_company,
	setup_loan_demand_offset_order,
)

CLASS_SAVEPOINT = "lending_test_class_data"


def with_days_past_due_repost(test):
	"""Run the backdated Days Past Due Log repost that LendingTestSuite skips by default"""
	return patch.object(
		loan_module, "repost_days_past_due_log", loan_module.repost_days_past_due_log
	)(test)


class BootStrapTestData:
	def __init__(self):
		self.make_presets()
		self.make_master_data()

	def make_presets(self):
		create_loan_accounts()
		setup_loan_demand_offset_order()

	def make_master_data(self):
		set_loan_settings_in_company()
		set_loan_accrual_frequency("Monthly")
		init_loan_products()
		self.make_flat_interest_rate_loan()
		create_loan_security_type()
		create_loan_security()
		create_loan_security_price(
			"Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
		)
		create_loan_security_price(
			"Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
		)
		init_customers()
		make_customer("_Test Loan Customer 2")
		frappe.db.commit()  # nosemgrep

	def make_flat_interest_rate_loan(self):
		create_loan_product(
			"Flat Interest Rate Loan",
			"Flat Interest Rate Loan",
			1000000,
			12,
			repayment_schedule_type="Flat Interest Rate",
		)


bootstrap = BootStrapTestData()


class LendingTestSuite(ERPNextTestSuite):
	"""Class for creating Lending test records

	Records built in `make_class_data` are created once per class and every test rolls back to them.
	"""

	# a backdated payment writes one Days Past Due Log per day up to today, so only classes that check DPD run it
	repost_days_past_due = False

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not cls.repost_days_past_due:
			cls.enterClassContext(patch.object(loan_module, "repost_days_past_due_log"))

		try:
			cls._set_up_class_data()
		except Exception:
			frappe.db.rollback()
			raise

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		super().tearDownClass()

	@classmethod
	def make_class_data(cls):
		pass

	@classmethod
	def reset_masters(cls):
		bootstrap.make_master_data()

	@classmethod
	def _set_up_class_data(cls):
		frappe.clear_cache()
		cls.make_class_data()
		frappe.db.savepoint(CLASS_SAVEPOINT)

	def tearDown(self):
		try:
			frappe.db.rollback(save_point=CLASS_SAVEPOINT)
		except Exception:
			# the test committed, so restore the masters and rebuild the class data
			super().tearDown()
			self.reset_masters()
			self._set_up_class_data()
			return

		frappe.db.before_commit.reset()
		frappe.db.after_commit.reset()
		frappe.db.run_after_transaction_callbacks(frappe.db.after_rollback)
		# redis_cache'd lookups like get_dpd_threshold_map can still hold the rolled back values
		frappe.clear_cache()
		frappe.local.request_cache.clear()
		if hasattr(frappe.local, "future_sle"):
			frappe.local.future_sle.clear()
