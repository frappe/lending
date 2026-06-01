import frappe
from frappe.utils import add_days, nowdate

from lending.loan_management.report.loan_security_ledger.loan_security_ledger import (
	execute,
	get_data,
)
from lending.tests.test_utils import (
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_secured_demand_loan,
)
from lending.tests.utils import LendingTestSuite


class TestLoanSecurityLedger(LendingTestSuite):
	def setUp(self):
		create_loan_security_type()
		create_loan_security()
		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 5), True)
		self.loan = create_secured_demand_loan("_Test Loan Customer", disbursement_amount=40000)

	def test_loan_security_ledger_requires_loan_or_applicant_filter(self):
		with self.assertRaises(frappe.ValidationError):
			get_data({})

	def test_loan_security_ledger_returns_expected_assignment_row(self):
		report = execute({"loan": self.loan.name, "applicant": "_Test Loan Customer"})
		columns, data = report

		required_columns = {"loan", "doctype", "loan_security", "loan_security_type", "qty"}
		self.assertTrue(required_columns.issubset({c.get("fieldname") for c in columns}))
		self.assertTrue(data)

		assignment_row = next(
			(row for row in data if row.get("doctype") == "Loan Security Assignment"),
			None,
		)
		self.assertIsNotNone(assignment_row, "Expected Loan Security Assignment row in ledger report")
		expected_data = {
			"doctype": "Loan Security Assignment",
			"loan": self.loan.name,
			"loan_security": "Test Security 1",
			"loan_security_type": "Stock",
			"qty": 4000.0,
		}
		for key, value in expected_data.items():
			self.assertEqual(assignment_row.get(key), value)
