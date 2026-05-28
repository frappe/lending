import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from lending.loan_management.report.loan_security_exposure.loan_security_exposure import (
	execute,
	get_columns,
	get_company_wise_loan_security_details,
)
from lending.tests.test_utils import (
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_secured_demand_loan,
	init_customers,
	master_init,
)


class TestLoanSecurityExposure(IntegrationTestCase):
	def setUp(self):
		for dt in ["Unpledge", "Pledge", "Loan Security Release", "Loan Security Assignment"]:
			frappe.db.delete(dt)
		frappe.db.commit()

		master_init()
		init_customers()
		create_loan_security_type()
		create_loan_security()
		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 5), True)
		create_secured_demand_loan("_Test Loan Customer", disbursement_amount=30000)

	def test_loan_security_exposure_aggregates_company_wise_security_details(self):
		security_map, total = get_company_wise_loan_security_details(
			{"company": "_Test Company"}, {}
		)
		self.assertIsInstance(security_map, dict)
		self.assertGreaterEqual(total, 0)

	def test_loan_security_exposure_returns_expected_row(self):
		report = execute({"company": "_Test Company"})
		columns, data = report

		self.assertTrue(len(columns) > 0)
		self.assertTrue(data)
		row = next(item for item in data if item.get("loan_security") == "Test Security 1")
		expected_data = {
			"loan_security": "Test Security 1",
			"loan_security_type": "Stock",
			"total_qty": 4000.0,
			"pledged_applicant_count": 1.0,
			"portfolio_percent": 100.0,
		}
		for key, value in expected_data.items():
			self.assertEqual(row.get(key), value)

	def test_loan_security_exposure_defines_columns(self):
		columns = get_columns({"company": "_Test Company"})
		self.assertGreater(len(columns), 5)
