import unittest

import frappe
from frappe.utils import getdate

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	process_interest_accrual_batch,
)
from lending.tests.test_utils import (
	create_loan,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)


class TestLoanInterestAccrual(unittest.TestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_accrual_in_batch_with_freeze_date(self):
		set_loan_accrual_frequency("Daily")

		posting_date = "2024-04-05"
		repayment_start_date = "2024-05-05"

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

		frappe.db.set_value("Loan", loan_a.name, {"freeze_account": 1, "freeze_date": "2024-04-10"})

		loan_batch = [get_loan_object(loan.load_from_db()) for loan in loans]

		process_interest_accrual_batch(
			loans=loan_batch,
			posting_date="2024-04-20",
			process_loan_interest="",
			accrual_type="Regular",
			accrual_date="2024-04-20",
		)

		last_accrual_date_a = frappe.db.get_value(
			"Loan Interest Accrual",
			{"loan": loan_a.name, "docstatus": 1},
			"MAX(posting_date)",
		)

		last_accrual_date_b = frappe.db.get_value(
			"Loan Interest Accrual",
			{"loan": loan_b.name, "docstatus": 1},
			"MAX(posting_date)",
		)

		self.assertEqual(getdate(last_accrual_date_a), getdate("2024-04-10"))
		self.assertEqual(getdate(last_accrual_date_b), getdate("2024-04-20"))


def get_loan_object(loan_doc):
	return frappe._dict(
		{
			"name": loan_doc.name,
			"total_payment": loan_doc.total_payment,
			"total_amount_paid": loan_doc.total_amount_paid,
			"debit_adjustment_amount": loan_doc.debit_adjustment_amount,
			"credit_adjustment_amount": loan_doc.credit_adjustment_amount,
			"refund_amount": loan_doc.refund_amount,
			"loan_account": loan_doc.loan_account,
			"interest_income_account": loan_doc.interest_income_account,
			"penalty_income_account": loan_doc.penalty_income_account,
			"loan_amount": loan_doc.loan_amount,
			"is_term_loan": loan_doc.is_term_loan,
			"status": loan_doc.status,
			"disbursement_date": loan_doc.disbursement_date,
			"disbursement_amount": loan_doc.disbursed_amount,
			"applicant_type": loan_doc.applicant_type,
			"applicant": loan_doc.applicant,
			"rate_of_interest": loan_doc.rate_of_interest,
			"total_interest_payable": loan_doc.total_interest_payable,
			"write_off_amount": loan_doc.written_off_amount,
			"total_principal_paid": loan_doc.total_principal_paid,
			"repayment_start_date": loan_doc.repayment_start_date,
			"company": loan_doc.company,
			"freeze_account": loan_doc.freeze_account,
			"freeze_date": loan_doc.freeze_date,
		}
	)
