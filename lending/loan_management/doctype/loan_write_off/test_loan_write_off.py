# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


from frappe.tests import IntegrationTestCase

from lending.tests.test_utils import (
	create_loan,
	create_loan_write_off,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)


class TestLoanWriteOff(IntegrationTestCase):
	def setUp(self):
		master_init()
		init_loan_products()

	def test_loan_write_off_status_on_submit_and_cancel(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		loan_write_1 = create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)
		loan.load_from_db()
		self.assertEqual(loan.status, "Written Off")

		loan_write_1.cancel()
		loan.load_from_db()
		self.assertEqual(loan.status, "Disbursed")

		loan_write_1 = create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)
		loan_write_2 = create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)

		loan.load_from_db()
		self.assertEqual(loan.status, "Written Off")

		loan_write_2.cancel()
		loan.load_from_db()
		self.assertEqual(loan.status, "Written Off")

		loan_write_1.cancel()
		loan.load_from_db()
		self.assertEqual(loan.status, "Disbursed")
