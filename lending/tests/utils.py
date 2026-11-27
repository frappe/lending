from unittest.mock import patch

import frappe
from frappe.test_runner import make_test_records
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from lending.loan_management.doctype.loan import loan as loan_module
from lending.tests.test_utils import (
	create_loan_accounts,
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
		# customer group and territory test records the loan customers link to
		make_test_records("Customer", commit=True)
		create_loan_accounts()
		setup_loan_demand_offset_order()

	def make_master_data(self):
		set_loan_settings_in_company()
		set_loan_accrual_frequency("Monthly")
		init_loan_products()
		create_loan_security_type()
		create_loan_security()
		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1))
		create_loan_security_price("Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1))
		init_customers()
		make_customer("_Test Loan Customer 2")
		frappe.db.commit()  # nosemgrep


bootstrap = None


class LendingTestSuite(FrappeTestCase):
	"""Class for creating Lending test records

	Records built in `make_class_data` are created once per class and every test rolls back to them.
	"""

	# a backdated payment writes one Days Past Due Log per day up to today, so only classes that check DPD run it
	repost_days_past_due = False

	@classmethod
	def setUpClass(cls):
		global bootstrap

		super().setUpClass()
		# not at import: frappe makes a module's test records only after importing it
		if not bootstrap:
			bootstrap = BootStrapTestData()

		if not cls.repost_days_past_due:
			patcher = patch.object(loan_module, "repost_days_past_due_log")
			patcher.start()
			cls.addClassCleanup(patcher.stop)

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
			frappe.db.rollback()
			self.reset_masters()
			self._set_up_class_data()
			return

		frappe.db.before_commit.reset()
		frappe.db.after_commit.reset()
		frappe.db.after_rollback.run()
		# redis_cache'd lookups like get_dpd_threshold_map can still hold the rolled back values
		frappe.clear_cache()
		frappe.local.request_cache.clear()
		if hasattr(frappe.local, "future_sle"):
			frappe.local.future_sle.clear()
