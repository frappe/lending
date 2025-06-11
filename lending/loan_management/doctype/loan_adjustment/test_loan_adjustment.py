# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

# import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_loan,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
	set_loan_accrual_frequency,
)


class TestLoanAdjustment(IntegrationTestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_loan_adjustment_submit(self):
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "excess_amount_acceptance_limit", 100)
		set_loan_accrual_frequency(loan_accrual_frequency="Daily")

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-04-05",
			posting_date="2024-02-20",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-02-20", repayment_start_date="2024-04-05"
		)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-04-04", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(loan=loan.name, posting_date="2024-04-05")

		doc = frappe.get_doc(
			{
				"doctype": "Loan Adjustment",
				"loan": loan.name,
				"posting_date": getdate(),
				"adjustments": [
					{
						"loan_repayment_type": "Interest Waiver",
						"amount": 721.92,
					}
				],
			}
		).insert()

		self.assertTrue(doc.submit())
