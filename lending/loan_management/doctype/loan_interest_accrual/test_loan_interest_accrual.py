import frappe
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, date_diff, flt, getdate

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	process_interest_accrual_batch,
)
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


class TestLoanInterestAccrual(IntegrationTestCase):
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

		LoanInterestAccrual = DocType("Loan Interest Accrual")

		last_accrual_date_a = (
			frappe.qb.from_(LoanInterestAccrual)
			.select(fn.Max(LoanInterestAccrual.posting_date))
			.where((LoanInterestAccrual.loan == loan_a.name) & (LoanInterestAccrual.docstatus == 1))
		).run()[0][0]

		last_accrual_date_b = (
			frappe.qb.from_(LoanInterestAccrual)
			.select(fn.Max(LoanInterestAccrual.posting_date))
			.where((LoanInterestAccrual.loan == loan_b.name) & (LoanInterestAccrual.docstatus == 1))
		).run()[0][0]

		self.assertEqual(getdate(last_accrual_date_a), getdate("2024-04-10"))
		self.assertEqual(getdate(last_accrual_date_b), getdate("2024-04-20"))

	def test_loc_loan_interest_accrual(self):
		set_loan_accrual_frequency("Daily")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			500000,
			"Repay Over Number of Periods",
			1,
			posting_date="2024-10-17",
			rate_of_interest=17,
			applicant_type="Customer",
			limit_applicable_start="2024-10-16",
			limit_applicable_end="2026-10-16",
		)
		loan.submit()

		disbursement_a = make_loan_disbursement_entry(
			loan.name,
			171000,
			disbursement_date="2024-11-30",
			repayment_start_date="2025-02-28",
			repayment_frequency="One Time",
		)
		disbursement_a.submit()

		disbursement_b = make_loan_disbursement_entry(
			loan.name,
			200000,
			disbursement_date="2024-12-01",
			repayment_start_date="2025-02-28",
			repayment_frequency="One Time",
		)
		disbursement_b.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-05", loan=loan.name, company="_Test Company"
		)

		loan_interest_accrual_1 = frappe.get_all(
			"Loan Interest Accrual",
			filters={
				"loan": loan.name,
				"loan_disbursement": disbursement_a.name,
				"docstatus": 1,
			},
			fields=["name", "posting_date"],
			order_by="posting_date asc",
		)

		loan_interest_accrual_2 = frappe.get_all(
			"Loan Interest Accrual",
			filters={
				"loan": loan.name,
				"loan_disbursement": disbursement_b.name,
				"docstatus": 1,
			},
			fields=["name", "posting_date"],
			order_by="posting_date asc",
		)

		self.assertEqual(
			len(loan_interest_accrual_1), date_diff("2024-12-05", disbursement_a.disbursement_date) + 1
		)
		self.assertEqual(
			len(loan_interest_accrual_2), date_diff("2024-12-05", disbursement_b.disbursement_date) + 1
		)

		self.assertEqual(
			getdate(loan_interest_accrual_1[0].posting_date), getdate(disbursement_a.disbursement_date)
		)
		self.assertEqual(
			getdate(loan_interest_accrual_2[0].posting_date), getdate(disbursement_b.disbursement_date)
		)

	def test_loan_interest_accruals_after_maturity_date(self):
		set_loan_accrual_frequency("Monthly")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			3,
			"Customer",
			posting_date="2024-03-25",
			rate_of_interest=12,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-03-25",
			repayment_start_date="2024-04-07",
			withhold_security_deposit=1,
		)

		process_daily_loan_demands(posting_date="2024-09-01", loan=loan.name)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-8-05", loan=loan.name, company="_Test Company"
		)

		maturity_date = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1}, "maturity_date"
		)

		LoanInterestAccrual = DocType("Loan Interest Accrual")
		last_accrual_date = (
			frappe.qb.from_(LoanInterestAccrual)
			.select(fn.Max(LoanInterestAccrual.posting_date))
			.where((LoanInterestAccrual.loan == loan.name) & (LoanInterestAccrual.docstatus == 1))
		).run()[0][0]

		self.assertEqual(getdate(last_accrual_date), add_days(getdate(maturity_date), -1))

		process_loan_interest_accrual_for_loans(
			posting_date="2024-8-05", loan=loan.name, company="_Test Company"
		)

		self.assertEqual(getdate(last_accrual_date), add_days(getdate(maturity_date), -1))

	def test_future_interest_amount(self):
		set_loan_accrual_frequency("Daily")
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			3,
			"Customer",
			posting_date="2024-03-25",
			rate_of_interest=12,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date="2024-03-25",
			repayment_start_date="2024-04-07",
			withhold_security_deposit=1,
		)

		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-03-27", company="_Test Company"
		)

		amounts = calculate_amounts(loan.name, "2024-04-06", payment_type="Loan Closure")

		no_of_days = date_diff("2024-04-06", "2024-03-27")
		interest_amount = 500000 * 12 * no_of_days / 36500

		self.assertEqual(flt(amounts.get("unaccrued_interest", 0), 2), flt(interest_amount, 2))

	def test_unbooked_interest_accrual_calculation_till_freeze_date(self):
		set_loan_accrual_frequency("Daily")

		posting_date = "2024-01-05"
		repayment_start_date = "2024-01-05"

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
			loan=loan.name, posting_date="2024-04-20", company="_Test Company"
		)
		freeze_date = "2024-04-10"

		LoanInterestAccrual = DocType("Loan Interest Accrual")

		accrual_sum_till_freeze_date = (
			frappe.qb.from_(LoanInterestAccrual)
			.select(fn.Sum(LoanInterestAccrual.interest_amount))
			.where(
				(LoanInterestAccrual.loan == loan.name)
				& (LoanInterestAccrual.docstatus == 1)
				& (LoanInterestAccrual.posting_date < freeze_date)
				& (LoanInterestAccrual.interest_type == "Normal Interest")
			)
		).run()[0][0] or 0

		frappe.db.set_value("Loan", loan.name, {"freeze_account": 1, "freeze_date": freeze_date})

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-04-20")

		self.assertEqual(accrual_sum_till_freeze_date, amounts["unbooked_interest"])
		self.assertEqual(amounts["unaccrued_interest"], 0)

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-04-25")

		self.assertEqual(accrual_sum_till_freeze_date, amounts["unbooked_interest"])
		self.assertEqual(amounts["unaccrued_interest"], 0)


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
