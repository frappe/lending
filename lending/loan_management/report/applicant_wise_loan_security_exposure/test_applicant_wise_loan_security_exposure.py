from frappe.utils import add_days, nowdate

from lending.loan_management.report.applicant_wise_loan_security_exposure.applicant_wise_loan_security_exposure import (
	execute,
	get_applicant_wise_total_loan_security_qty,
	get_columns,
)
from lending.tests.test_utils import (
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_secured_demand_loan,
)
from lending.tests.utils import LendingTestSuite


class TestApplicantWiseLoanSecurityExposure(LendingTestSuite):
	def setUp(self):
		create_loan_security_type()
		create_loan_security()
		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 5), True)
		create_secured_demand_loan("_Test Loan Customer", disbursement_amount=30000)

	def test_applicant_wise_loan_security_exposure_aggregates_applicant_qty(self):
		current_pledges, total_value_map, applicant_type_map = get_applicant_wise_total_loan_security_qty(
			{"company": "_Test Company"}, {}
		)
		self.assertIsInstance(current_pledges, dict)
		self.assertIsInstance(total_value_map, dict)
		self.assertIsInstance(applicant_type_map, dict)
		security_key = ("_Test Loan Customer", "Test Security 1")
		self.assertIn(security_key, current_pledges)
		self.assertEqual(current_pledges.get(security_key), 4000.0)

	def test_applicant_wise_loan_security_exposure_returns_expected_row(self):
		report = execute({"company": "_Test Company"})
		columns, data = report

		required_columns = {
			"applicant_type",
			"applicant_name",
			"loan_security",
			"total_qty",
			"portfolio_percent",
		}
		self.assertTrue(required_columns.issubset({c.get("fieldname") for c in columns}))
		self.assertTrue(data)
		row = next((item for item in data if item.get("applicant_name") == "_Test Loan Customer"), None)
		self.assertIsNotNone(row, "Expected row for created applicant in exposure report")
		expected_data = {
			"applicant_type": "Customer",
			"applicant_name": "_Test Loan Customer",
			"loan_security": "Test Security 1",
			"total_qty": 4000.0,
		}
		for key, value in expected_data.items():
			self.assertEqual(row.get(key), value)
		self.assertAlmostEqual(row.get("portfolio_percent"), 100.0, places=2)

	def test_applicant_wise_loan_security_exposure_defines_columns(self):
		columns = get_columns({"company": "_Test Company"})
		required_columns = {
			"applicant_type",
			"applicant_name",
			"loan_security",
			"total_qty",
			"portfolio_percent",
		}
		self.assertTrue(required_columns.issubset({c.get("fieldname") for c in columns}))
