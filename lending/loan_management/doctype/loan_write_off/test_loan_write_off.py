# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import get_datetime

from lending.tests.test_utils import (
	create_loan,
	create_loan_write_off,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)
from lending.tests.utils import LendingTestSuite


class TestLoanWriteOff(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()

	def test_loan_write_off_status_on_submit_and_cancel(self):
		loan = create_loan(
			"_Test Customer 2",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			4,
			"Customer",
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		loan_write_1 = create_loan_write_off(loan.name, "2024-11-05", write_off_amount=50000)
		loan.load_from_db()
		self.assertEqual(loan.status, "Written Off")

		loan_write_1.cancel()
		loan.load_from_db()
		self.assertEqual(loan.status, "Disbursed")

		loan_write_1 = create_loan_write_off(loan.name, "2024-11-05", write_off_amount=50000)
		loan_write_2 = create_loan_write_off(loan.name, "2024-11-05", write_off_amount=50000)

		loan.load_from_db()
		self.assertEqual(loan.status, "Written Off")

		loan_write_2.cancel()
		loan.load_from_db()
		self.assertEqual(loan.status, "Written Off")

		loan_write_1.cancel()
		loan.load_from_db()
		self.assertEqual(loan.status, "Disbursed")

		loan_repayments = frappe.db.get_all(
			"Loan Repayment",
			filters={
				"against_loan": loan.name,
				"value_date": ("<=", get_datetime("2024-11-05")),
				"docstatus": 2,
				"is_write_off_waiver": 1,
			},
			pluck="name",
		)
		self.assertEqual(len(loan_repayments), 2)

