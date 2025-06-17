# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
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

	def test_validation_error_on_excess_adjustment_amount(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			"Customer",
			posting_date="2024-03-25",
			rate_of_interest=12,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-03-25",
			repayment_start_date="2024-04-01",
			withhold_security_deposit=1,
		)

		process_daily_loan_demands(posting_date="2024-09-01", loan=loan.name)

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-09-01")
		payable_amount = round(float(amounts["payable_amount"] or 0.0), 2)

		repayment_entry = create_repayment_entry(loan.name, "2024-09-01", payable_amount)
		repayment_entry.submit()

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-09-05")
		total_net_payable = round(
			float(amounts["unaccrued_interest"] or 0.0)
			+ float(amounts["interest_amount"] or 0.0)
			+ float(amounts["penalty_amount"] or 0.0)
			+ float(amounts["total_charges_payable"] or 0.0)
			- float(amounts["available_security_deposit"] or 0.0)
			+ float(amounts["unbooked_interest"] or 0.0)
			+ float(amounts["unbooked_penalty"] or 0.0)
			+ float(amounts["pending_principal_amount"] or 0.0),
			2,
		)

		loan_adjustment = frappe.get_doc(
			{
				"doctype": "Loan Adjustment",
				"loan": loan.name,
				"posting_date": "2024-09-05",
				"foreclosure_type": "Internal Foreclosure",
				"adjustments": [
					{"loan_repayment_type": "Normal Repayment", "amount": total_net_payable + 1000}
				],
			}
		)

		self.assertRaises(frappe.ValidationError, loan_adjustment.save)
