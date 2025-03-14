# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from collections import Counter

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, get_datetime, nowdate

from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)


class TestLoanRepayment(IntegrationTestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_in_between_payments(self):
		posting_date = get_datetime("2024-04-18")
		repayment_start_date = get_datetime("2024-05-05")
		loan_a = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan_b = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loans = [loan_a, loan_b]
		for loan in loans:
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=posting_date,
				repayment_start_date=repayment_start_date,
			)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=add_months(posting_date, 6), company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=add_months(repayment_start_date, 6))

		create_repayment_entry(
			loan=loan_a.name, posting_date=repayment_start_date, paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name,
			posting_date=add_months(repayment_start_date, 1),
			paid_amount=178025,
		).submit()

		create_repayment_entry(
			loan=loan_b.name, posting_date=repayment_start_date, paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 1), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()

		dates = [add_months(repayment_start_date, i) for i in range(5)]
		for date in dates:
			repayment_a = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_a.name, "posting_date": date}
			)
			repayment_b = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_b.name, "posting_date": date}
			)

			self.assertEqual(repayment_a.principal_amount_paid, repayment_b.principal_amount_paid)
			self.assertEqual(repayment_a.pending_principal_amount, repayment_b.pending_principal_amount)
			self.assertEqual(repayment_a.interest_payable, repayment_b.interest_payable)

	def test_in_between_cancellations(self):
		posting_date = get_datetime("2024-04-18")
		repayment_start_date = get_datetime("2024-05-05")
		loan_a = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan_b = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loans = [loan_a, loan_b]
		for loan in loans:
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=posting_date,
				repayment_start_date=repayment_start_date,
			)
			process_loan_interest_accrual_for_loans(
				loan=loan.name, posting_date=add_months(posting_date, 6), company="_Test Company"
			)
			process_daily_loan_demands(loan=loan.name, posting_date=add_months(repayment_start_date, 6))

		create_repayment_entry(
			loan=loan_a.name, posting_date=repayment_start_date, paid_amount=178025
		).submit()
		entry_to_be_deleted = create_repayment_entry(
			loan=loan_a.name,
			posting_date=add_months(repayment_start_date, 1),
			paid_amount=178025,
		)
		entry_to_be_deleted.submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_a.name, posting_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()
		entry_to_be_deleted.load_from_db()
		entry_to_be_deleted.cancel()

		create_repayment_entry(
			loan=loan_b.name, posting_date=repayment_start_date, paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 3), paid_amount=178025
		).submit()
		create_repayment_entry(
			loan=loan_b.name, posting_date=add_months(repayment_start_date, 4), paid_amount=178025
		).submit()

		dates = [add_months(repayment_start_date, i) for i in [0, 2, 3, 4]]
		for date in dates:
			repayment_a = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_a.name, "posting_date": date}
			)
			repayment_b = frappe.get_doc(
				"Loan Repayment", {"docstatus": 1, "against_loan": loan_b.name, "posting_date": date}
			)

			self.assertEqual(repayment_a.principal_amount_paid, repayment_b.principal_amount_paid)
			self.assertEqual(repayment_a.pending_principal_amount, repayment_b.pending_principal_amount)
			self.assertEqual(repayment_a.interest_payable, repayment_b.interest_payable)

	def test_reverse_accruals_and_demands(self):
		posting_date = "2024-04-18"
		repayment_start_date = "2024-05-05"
		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			applicant_type="Customer",
			repayment_start_date=repayment_start_date,
			posting_date=posting_date,
			rate_of_interest=23,
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=posting_date,
			repayment_start_date=repayment_start_date,
		)
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date=nowdate(), company="_Test Company"
		)
		process_daily_loan_demands(loan=loan.name, posting_date=add_months(repayment_start_date, 6))
		create_repayment_entry(
			loan=loan.name, posting_date=repayment_start_date, paid_amount=178025
		).submit()
		entry_to_be_deleted = create_repayment_entry(
			loan=loan.name,
			posting_date=add_months(repayment_start_date, 1),
			paid_amount=178025,
		)
		entry_to_be_deleted.submit()
		create_repayment_entry(
			loan=loan.name, posting_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()
		entry_to_be_deleted.load_from_db()
		entry_to_be_deleted.cancel()

		create_repayment_entry(
			loan=loan.name, posting_date=add_months(repayment_start_date, 2), paid_amount=178025
		).submit()

		def check_reversed_entries(reversed_entries):
			reversed_entries_stack = Counter()
			for reversed_entry in reversed_entries:
				if reversed_entry.docstatus == 1:
					reversed_entries_stack[reversed_entry.posting_date] += 1
				elif reversed_entry.docstatus == 2:
					if reversed_entry.posting_date not in reversed_entries_stack:
						break
					self.assertTrue(reversed_entry.posting_date in reversed_entries_stack)
					reversed_entries_stack[reversed_entry.posting_date] -= 1
			for posting_date in reversed_entries_stack:
				self.assertEqual(reversed_entries_stack[posting_date], 0)

		check_reversed_entries(reversed_accruals)
		check_reversed_entries(reversed_demands)
