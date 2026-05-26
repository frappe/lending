# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from lending.tests.test_utils import (
	create_loan,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)
from lending.tests.utils import LendingTestSuite


class TestLoanDisbursement(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()

	def test_sales_invoice_created_on_loan_disbursement_with_charges(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			2,
			"Customer",
			"2024-07-15",
			"2024-06-25",
			10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-06-25",
			repayment_start_date="2024-07-15",
			loan_disbursement_charges=[{"charge": "Processing Fee", "amount": 5000}],
		)

		invoices = frappe.get_all(
			"Sales Invoice",
			filters={
				"docstatus": 1,
				"customer": "_Test Customer 1",
				"loan": loan.name,
			},
		)

		self.assertTrue(
			len(invoices) == 1, "Expected 1 Sales Invoice to be created for Loan Disbursement charge."
		)

	def test_tranche_number_assignment_on_loan_disbursement(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			2,
			"Customer",
			"2024-07-15",
			"2024-06-25",
			10,
		)
		loan.submit()

		disbursement_1 = make_loan_disbursement_entry(
			loan.name,
			50000,
			disbursement_date="2024-07-15",
			repayment_start_date="2024-08-05",
		)

		disbursement_2 = make_loan_disbursement_entry(
			loan.name,
			30000,
			disbursement_date="2024-07-20",
			repayment_start_date="2024-08-05",
		)

		disbursement_3 = make_loan_disbursement_entry(
			loan.name,
			20000,
			disbursement_date="2024-07-10",
			repayment_start_date="2024-08-05",
		)

		disbursement_1.load_from_db()
		disbursement_2.load_from_db()
		disbursement_3.load_from_db()

		self.assertEqual(disbursement_1.tranche_number, 2)
		self.assertEqual(disbursement_2.tranche_number, 3)
		self.assertEqual(disbursement_3.tranche_number, 1)

		schedules_before = frappe.get_all(
			"Loan Repayment Schedule",
			filters={"loan": loan.name, "docstatus": 1},
			fields=["status", "loan_disbursement"],
		)
		status_map_before = {s.loan_disbursement: s.status for s in schedules_before}

		self.assertEqual(status_map_before.get(disbursement_1.name), "Outdated")
		self.assertEqual(status_map_before.get(disbursement_2.name), "Active")
		self.assertEqual(status_map_before.get(disbursement_3.name), "Outdated")

		disbursement_3.cancel()

		disbursement_1.load_from_db()
		disbursement_2.load_from_db()
		disbursement_3.load_from_db()

		self.assertEqual(disbursement_1.tranche_number, 1)
		self.assertEqual(disbursement_2.tranche_number, 2)
		self.assertEqual(disbursement_3.tranche_number, 0)

		schedules_after = frappe.get_all(
			"Loan Repayment Schedule",
			filters={"loan": loan.name, "docstatus": 1},
			fields=["status", "loan_disbursement"],
		)
		status_map_after = {s.loan_disbursement: s.status for s in schedules_after}

		self.assertEqual(status_map_after.get(disbursement_1.name), "Outdated")
		self.assertEqual(status_map_after.get(disbursement_2.name), "Active")
