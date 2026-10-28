# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from lending.tests.test_utils import (
	create_loan,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)


class TestLoanDisbursement(FrappeTestCase):
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

	def test_cancel_on_loan_disbursement_with_missing_repayment_schedule(self):
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

		disbursement = make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-06-25",
			repayment_start_date="2024-07-15",
		)

		schedule_name = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan_disbursement": disbursement.name, "docstatus": 1},
			"name",
		)
		schedule = frappe.get_doc("Loan Repayment Schedule", schedule_name)

		self.assertRaises(frappe.ValidationError, schedule.cancel)

		frappe.db.sql("delete from `tabRepayment Schedule` where parent=%s", schedule_name)
		frappe.db.sql("delete from `tabLoan Repayment Schedule` where name=%s", schedule_name)

		disbursement.cancel()

		disbursement.load_from_db()
		loan.reload()
		self.assertEqual(disbursement.docstatus, 2)
		self.assertEqual(loan.status, "Sanctioned")
		self.assertEqual(loan.total_payment, 0)
		self.assertEqual(loan.total_interest_payable, 0)
