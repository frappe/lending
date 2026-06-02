import frappe
from frappe.utils import add_days, nowdate

from erpnext.tests.utils import ERPNextTestSuite

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


BootStrapTestData()


class LendingTestSuite(ERPNextTestSuite):
	"""Class for creating Lending test records"""

	pass
