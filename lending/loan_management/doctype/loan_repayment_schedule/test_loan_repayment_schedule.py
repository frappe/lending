# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import date_diff

from lending.loan_management.doctype.loan_repayment_schedule.utils import (
	get_amounts,
	get_monthly_repayment_amount,
)
from lending.loan_management.doctype.loan_restructure.loan_restructure import create_loan_repayment
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.tests.test_utils import (
	create_loan,
	create_repayment_entry,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)


class TestLoanRepaymentSchedule(IntegrationTestCase):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()
		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")

	def test_correct_moratorium_periods_after_restructure(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			285000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-12-05",
			posting_date="2024-11-05",
			rate_of_interest=17,
			applicant_type="Customer",
			moratorium_tenure=3,
			moratorium_type="Principal",
		)
		loan.submit()
		loan.load_from_db()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-11-05", repayment_start_date="2024-12-05"
		)
		process_daily_loan_demands(loan=loan.name, posting_date="2025-12-05")
		loan_demand_amount = 181958
		repayment_entry = create_repayment_entry(
			loan=loan.name,
			posting_date="2025-12-05",
			paid_amount=loan_demand_amount + 1000,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()
		repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1}
		)
		repayment_schedule_rows = repayment_schedule.get("repayment_schedule")
		num_of_rows = len(repayment_schedule_rows)
		self.assertEqual(num_of_rows, 15)
		monthly_repayment_amount = get_monthly_repayment_amount(285000, 17, 12, "Monthly")
		self.assertTrue(
			abs(repayment_schedule_rows[-1].total_payment - (monthly_repayment_amount + 1000) < 1000)
		)
