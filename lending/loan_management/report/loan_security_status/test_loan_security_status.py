from frappe.utils import add_days, nowdate

from lending.loan_management.report.loan_security_status.loan_security_status import (
	execute,
	get_conditions,
)
from lending.tests.test_utils import (
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_secured_demand_loan,
)
from lending.tests.utils import LendingTestSuite


class TestLoanSecurityStatus(LendingTestSuite):
	def setUp(self):
		create_loan_security_type()
		create_loan_security()
		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 5), True)
		self.loan = create_secured_demand_loan("_Test Loan Customer", disbursement_amount=50000)

	def test_loan_security_status_builds_filter_conditions(self):
		conditions = get_conditions({"applicant": "APP-1", "pledge_status": "Pledged"})
		self.assertIn("p.applicant", conditions)
		self.assertIn("p.status", conditions)

	def test_loan_security_status_returns_expected_row(self):
		report = execute({"company": "_Test Company", "applicant": "_Test Loan Customer"})
		columns, data = report

		required_columns = {
			"loan_security_assignment",
			"loan",
			"applicant",
			"status",
			"loan_security",
			"qty",
		}
		self.assertTrue(required_columns.issubset({c.get("fieldname") for c in columns}))
		self.assertTrue(data)
		row = next((item for item in data if item.get("loan") == self.loan.name), None)
		self.assertIsNotNone(row, "Expected row for created loan in loan security status report")
		expected_data = {
			"loan": self.loan.name,
			"applicant": "_Test Loan Customer",
			"status": "Pledged",
			"loan_security": "Test Security 1",
			"qty": 4000.0,
		}
		for key, value in expected_data.items():
			self.assertEqual(row.get(key), value)
