# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import add_days, add_months, date_diff, flt, get_datetime, getdate

from lending.loan_management.doctype.loan.loan import request_loan_closure, unpledge_security
from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
	get_disbursal_amount,
)
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	days_in_year,
)
from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.tests.test_utils import (
	create_demand_loan,
	create_loan,
	create_loan_application,
	create_loan_partner,
	create_loan_with_security,
	create_repayment_entry,
	create_secured_demand_loan,
	loan_classification_ranges,
	make_loan_disbursement_entry,
)
from lending.tests.utils import LendingTestSuite


class TestLoan(LendingTestSuite):
	applicant1 = "_Test Loan Customer 2"
	applicant2 = "_Test Loan Customer"
	applicant3 = "_Test Loan Customer 1"

	@classmethod
	def make_class_data(cls):
		loan_classification_ranges()

	def test_loan_with_repayment_periods(self):
		posting_date = "2025-01-27"
		loan = create_loan(
			self.applicant1,
			"Personal Loan",
			280000,
			"Repay Over Number of Periods",
			repayment_periods=20,
			repayment_start_date=add_months(posting_date, 1),
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			280000,
			repayment_start_date=add_months(posting_date, 1),
			disbursement_date=posting_date,
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		loan.load_from_db()
		self.assertEqual(loan_repayment_schedule.monthly_repayment_amount, 15052)
		self.assertEqual(flt(loan.total_interest_payable, 0), 20970)
		self.assertEqual(flt(loan.total_payment, 0), 300970)
		self.assertEqual(len(schedule), 20)

		for idx, principal_amount, interest_amount, balance_loan_amount in [
			[3, 13392, 1660, 226979],
			[19, 14875, 106, 0],
			[17, 14745, 307, 29715],
		]:
			self.assertEqual(flt(schedule[idx].principal_amount, 0), principal_amount)
			self.assertEqual(flt(schedule[idx].interest_amount, 0), interest_amount)
			self.assertEqual(flt(schedule[idx].balance_loan_amount, 0), balance_loan_amount)

	def test_loan_with_fixed_amount_per_period(self):
		disbursement_date = "2020-10-01"
		loan = create_loan(
			self.applicant1,
			"Personal Loan",
			280000,
			"Repay Fixed Amount per Period",
			monthly_repayment_amount=14000,
			repayment_start_date=add_months(disbursement_date, 1),
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			280000,
			repayment_start_date=add_months(disbursement_date, 1),
			disbursement_date=disbursement_date,
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)

		loan.load_from_db()
		self.assertEqual(len(loan_repayment_schedule.repayment_schedule), 22)
		self.assertEqual(flt(loan.total_interest_payable, 0), 22708)
		self.assertEqual(flt(loan.total_payment, 0), 302708)

	def test_loan_with_security(self):
		pledge = [
			{
				"loan_security": "Test Security 1",
				"qty": 4000.00,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledge, "Repay Over Number of Periods", 12
		)
		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertEqual(loan.loan_amount, 1000000)

	def test_loan_disbursement(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledge, "Repay Over Number of Periods", 12
		)

		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertEqual(loan.loan_amount, 1000000)

		loan.submit()

		loan_disbursement_entry1 = make_loan_disbursement_entry(loan.name, 500000)
		loan_disbursement_entry2 = make_loan_disbursement_entry(loan.name, 500000)

		loan = frappe.get_doc("Loan", loan.name)
		gl_entries1 = frappe.db.get_all(
			"GL Entry",
			fields=["name"],
			filters={"voucher_type": "Loan Disbursement", "voucher_no": loan_disbursement_entry1.name},
		)

		gl_entries2 = frappe.db.get_all(
			"GL Entry",
			fields=["name"],
			filters={"voucher_type": "Loan Disbursement", "voucher_no": loan_disbursement_entry2.name},
		)

		self.assertEqual(loan.status, "Disbursed")
		self.assertEqual(loan.disbursed_amount, 1000000)
		self.assertTrue(gl_entries1)
		self.assertTrue(gl_entries2)

	def test_sanctioned_amount_limit(self):
		# Clear loan docs before checking
		frappe.db.sql("DELETE FROM `tabLoan` where applicant = '_Test Loan Customer 1'")
		frappe.db.sql("DELETE FROM `tabLoan Application` where applicant = '_Test Loan Customer 1'")
		frappe.db.sql(
			"DELETE FROM `tabLoan Security Assignment` where applicant = '_Test Loan Customer 1'"
		)

		if not frappe.db.get_value(
			"Sanctioned Loan Amount",
			filters={
				"applicant_type": "Customer",
				"applicant": "_Test Loan Customer 1",
				"company": "_Test Company",
			},
		):
			frappe.get_doc(
				{
					"doctype": "Sanctioned Loan Amount",
					"applicant_type": "Customer",
					"applicant": "_Test Loan Customer 1",
					"sanctioned_amount_limit": 1500000,
					"company": "_Test Company",
				}
			).insert(ignore_permissions=True)

		# Make First Loan
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant3, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)
		loan = create_demand_loan(
			self.applicant3, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		# Make second loan greater than the sanctioned amount
		loan_application = create_loan_application(
			"_Test Company", self.applicant3, "Demand Loan", pledge, do_not_save=True
		)
		self.assertRaises(frappe.ValidationError, loan_application.save)

	def test_foreclosure_loan_process(self):
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

		process_loan_interest_accrual_for_loans(
			posting_date="2024-10-05", loan=loan.name, company="_Test Company"
		)

		loan.load_from_db()
		loan.freeze_account = 1
		loan.freeze_date = "2024-09-03"
		loan.save()

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
				"adjustments": [{"loan_repayment_type": "Normal Repayment", "amount": total_net_payable}],
			}
		)
		loan_adjustment.submit()

		last_accrual_date = frappe.db.get_value(
			"Loan Interest Accrual",
			{"loan": loan.name, "docstatus": 1},
			"posting_date",
			order_by="posting_date desc",
		)

		freeze_date = loan.freeze_date
		self.assertEqual(getdate(last_accrual_date), getdate(freeze_date))

		loan_status = frappe.db.get_value("Loan", loan.name, "status")
		self.assertEqual(loan_status, "Closed")

	def test_loan_repayment_for_term_loan(self):
		pledges = [
			{"loan_security": "Test Security 2", "qty": 4000.00},
			{"loan_security": "Test Security 1", "qty": 2000.00},
		]
		posting_date = "2025-01-30"
		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)
		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2,
			"Stock Loan",
			"Repay Over Number of Periods",
			12,
			loan_application,
			posting_date=add_months(posting_date, -1),
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=add_months(posting_date, -1),
			repayment_start_date=posting_date,
		)

		process_daily_loan_demands(loan=loan.name, posting_date=posting_date)

		repayment_entry = create_repayment_entry(loan.name, posting_date, 89768.75)

		repayment_entry.submit()

		# amounts = frappe.db.get_value(
		# 	"Loan Interest Accrual", {"loan": loan.name}, ["paid_interest_amount", "paid_principal_amount"]
		# )

		LoanDemand = DocType("Loan Demand")

		amounts = (
			frappe.qb.from_(LoanDemand)
			.select(
				fn.Sum(LoanDemand.paid_amount).as_("paid_amount"),
			)
			.where(
				(LoanDemand.loan == loan.name)
				& (LoanDemand.demand_type == "EMI")
				& (LoanDemand.demand_subtype == "Interest")
			)
		).run(as_dict=True)

		self.assertEqual(flt(amounts[0].paid_amount, 2), 11465.75)
		self.assertEqual(flt(repayment_entry.principal_amount_paid, 2), 78303.00)

	def test_partial_loan_security_release(self):
		pledge = [
			{"loan_security": "Test Security 1", "qty": 2000.00},
			{"loan_security": "Test Security 2", "qty": 4000.00},
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(
			posting_date=last_date, loan=loan.name, company="_Test Company"
		)

		repayment_entry = create_repayment_entry(loan.name, add_days(last_date, 5), 600000)
		repayment_entry.submit()

		unpledge_map = {"Test Security 2": 2000}

		unpledge_request = unpledge_security(loan=loan.name, security_map=unpledge_map, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		unpledge_request.submit()
		unpledge_request.load_from_db()
		self.assertEqual(unpledge_request.docstatus, 1)

	def test_disbursal_check_without_shortfall(self):
		pledges = [
			{
				"loan_security": "Test Security 2",
				"qty": 8000.00,
				"haircut": 50,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)

		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()

		# Disbursing 7,00,000 from the allowed 10,00,000 according to security pledge
		make_loan_disbursement_entry(loan.name, 700000)

		self.assertEqual(get_disbursal_amount(loan.name), (300000, 700000))

	def test_loan_repayment_against_partially_disbursed_loan(self):
		loan = create_secured_demand_loan(self.applicant2, disbursement_amount=500000)
		loan.load_from_db()

		self.assertEqual(loan.status, "Partially Disbursed")
		create_repayment_entry(loan.name, add_days("2019-10-30", 5), flt(loan.loan_amount / 3))

	def test_term_loan_schedule_types(self):
		def _create_loan_for_schedule(loan_product, repayment_method, monthly_repayment_amount=None):
			loan = create_loan(
				self.applicant1,
				loan_product,
				12000,
				repayment_method,
				12,
				repayment_start_date="2022-10-17",
				monthly_repayment_amount=monthly_repayment_amount,
			)

			loan.posting_date = "2022-10-17"
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=loan.posting_date,
				repayment_start_date="2022-10-17",
			)

			loan_repayment_schedule = frappe.get_doc("Loan Repayment Schedule", {"loan": loan.name})
			schedule = loan_repayment_schedule.repayment_schedule

			return schedule

		schedule = _create_loan_for_schedule("Term Loan Product 1", "Repay Over Number of Periods")

		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-17"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-17"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-17"))

		schedule = _create_loan_for_schedule("Term Loan Product 2", "Repay Over Number of Periods")
		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-11-01"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-12-01"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-10-01"))

		schedule = _create_loan_for_schedule("Term Loan Product 3", "Repay Over Number of Periods")
		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-31"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-30"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-30"))

		schedule = _create_loan_for_schedule("Term Loan Product 3", "Repay Over Number of Periods")
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-31"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-30"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-30"))

	def test_advance_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-01",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-04-01", repayment_start_date="2024-05-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 47523)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-29", 47523, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		lrs = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)

		self.assertEqual(lrs.monthly_repayment_amount, 47523)
		self.assertEqual(lrs.get("repayment_schedule")[3].total_payment, 47523)
		self.assertEqual(lrs.broken_period_interest, 0)
		self.assertEqual(lrs.broken_period_interest_days, 0)
		self.assertEqual(lrs.repayment_periods, 12)

	def test_multi_tranche_disbursement_accrual(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-18",
			rate_of_interest=23,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			500000,
			disbursement_date=getdate("2024-04-18"),
			repayment_start_date=getdate("2024-05-05"),
		)

		make_loan_disbursement_entry(
			loan.name,
			300000,
			disbursement_date=getdate("2024-05-10"),
			repayment_start_date=getdate("2024-06-05"),
		)

		make_loan_disbursement_entry(
			loan.name,
			200000,
			disbursement_date=getdate("2024-06-10"),
			repayment_start_date=getdate("2024-07-05"),
		)

	def test_hybrid_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-01",
			rate_of_interest=28,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-01", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 8253)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-29", 50000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

		repayment_entry.load_from_db()

		self.assertEqual(len(repayment_entry.get("repayment_details")), 2)

	def test_colender_loan_with_repayment_periods(self):
		loan_partner = "Test Loan Partner 1"

		if not frappe.db.exists("Loan Partner", loan_partner):
			create_loan_partner(
				"Test Loan Partner 1",
				"Test Loan Partner 1",
				partner_loan_share_percentage=80,
				effective_date="2025-01-27",
				repayment_schedule_type="EMI (PMT) based",
				partner_base_interest_rate=10,
				organization_type="Centralized",
				fldg_limit_calculation_component="Disbursement",
				type_of_fldg_applicable="Fixed Deposit Only",
				fldg_fixed_deposit_percentage=10,
			)

		posting_date = "2025-01-27"
		loan = create_loan(
			self.applicant1,
			"Personal Loan",
			280000,
			"Repay Over Number of Periods",
			loan_partner=loan_partner,
			repayment_periods=20,
			repayment_start_date=add_months(posting_date, 1),
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			280000,
			repayment_start_date=add_months(posting_date, 1),
			disbursement_date=posting_date,
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		self.assertEqual(len(schedule), loan_repayment_schedule.repayment_periods)

	def test_penalty(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-01",
			penalty_charges_rate=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-04-01", repayment_start_date="2024-05-05"
		)
		process_daily_loan_demands(posting_date="2024-07-06", loan=loan.name)
		process_loan_interest_accrual_for_loans(
			posting_date="2024-07-06", loan=loan.name, company="_Test Company"
		)

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-07-06")
		self.assertEqual(flt(amounts["penalty_amount"], 2), 3059.7)

	def test_additional_interest(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		# Process Loan Interest Accrual
		process_loan_interest_accrual_for_loans(
			posting_date="2024-05-10", loan=loan.name, company="_Test Company"
		)


class TestDemandLoan(LendingTestSuite):
	applicant2 = "_Test Loan Customer"

	@classmethod
	def make_class_data(cls):
		loan_classification_ranges()

		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]
		loan_application = create_loan_application(
			"_Test Company", cls.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			cls.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()
		cls.loan = loan.name

	def test_loan_closure(self):
		loan = frappe.get_doc("Loan", self.loan)

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		# Adding 5 since repayment is made 5 days late after due date
		# and since payment type is loan closure so interest should be considered for those
		# 5 days as well though in grace period

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * 34) / (36500)
		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(
			posting_date=add_days(last_date, 4), loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date=add_days(last_date, 5), loan=loan.name)
		repayment_entry = create_repayment_entry(
			loan.name,
			add_days(last_date, 5),
			flt(loan.loan_amount + accrued_interest_amount),
		)

		repayment_entry.submit()

		LoanDemand = DocType("Loan Demand")

		amounts = (
			frappe.qb.from_(LoanDemand)
			.select(
				fn.Sum(LoanDemand.demand_amount).as_("payable_amount"),
			)
			.where(
				(LoanDemand.loan == loan.name)
				& (LoanDemand.demand_type == "Normal")
				& (LoanDemand.demand_subtype == "Interest")
			)
		).run(as_dict=True)

		self.assertEqual(flt(amounts[0].payable_amount, 0), flt(accrued_interest_amount, 0))
		self.assertEqual(flt(repayment_entry.penalty_amount, 5), 0)

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

	def test_loan_security_release(self):
		loan = frappe.get_doc("Loan", self.loan)

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(
			posting_date=last_date, loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date=last_date, loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name,
			last_date,
			flt(loan.loan_amount + accrued_interest_amount),
		)
		repayment_entry.submit()

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

		unpledge_request = unpledge_security(loan=loan.name, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		loan.load_from_db()

		pledged_qty = get_pledged_security_qty(loan=loan.name)

		self.assertEqual(loan.status, "Closed")
		self.assertEqual(sum(pledged_qty.values()), 0)

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))

		self.assertEqual(amounts["pending_principal_amount"], 0)
		self.assertEqual(amounts["payable_principal_amount"], 0.0)
		self.assertEqual(amounts["interest_amount"], 0)

	def test_sanctioned_loan_security_release(self):
		loan = frappe.get_doc("Loan", self.loan)

		self.assertEqual(loan.loan_amount, 1000000)

		unpledge_map = {"Test Security 1": 4000}
		unpledge_request = unpledge_security(loan=loan.name, security_map=unpledge_map, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		unpledge_request.submit()

	def test_pending_loan_amount_after_closure_request(self):
		loan = frappe.get_doc("Loan", self.loan)

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		no_of_days += 5

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(
			posting_date=last_date, loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date=last_date, loan=loan.name)

		amounts = calculate_amounts(loan.name, add_days(last_date, 5), payment_type="Loan Closure")

		repayment_entry = create_repayment_entry(
			loan.name, add_days(last_date, 5), amounts["payable_amount"]
		)
		repayment_entry.submit()
		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))
		self.assertEqual(amounts["pending_principal_amount"], 0.0)


class TestAdvancePaymentDemands(LendingTestSuite):
	applicant1 = "_Test Loan Customer 2"

	@classmethod
	def make_class_data(cls):
		loan_classification_ranges()

		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			cls.applicant1,
			"Term Loan Product 4",
			1200000,
			"Repay Over Number of Periods",
			36,
			repayment_start_date="2024-06-05",
			posting_date="2024-05-03",
			rate_of_interest=29,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-05-03", repayment_start_date="2024-06-05"
		)
		process_daily_loan_demands(posting_date="2024-06-05", loan=loan.name)
		cls.loan = loan.name

	def test_multiple_advance_payment(self):
		loan = frappe.get_doc("Loan", self.loan)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-06-05", 50287)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-06-18", 50287, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-12-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-12-05", 251435)
		repayment_entry.submit()

		repayment_entry1 = create_repayment_entry(
			loan.name, "2024-12-21 00:00:00", 150287, repayment_type="Pre Payment"
		)
		repayment_entry1.submit()

		repayment_entry2 = create_repayment_entry(
			loan.name, "2024-12-21 00:00:20", 150287, repayment_type="Pre Payment"
		)
		repayment_entry2.submit()

		# Cancel the entry to check if correct schedule becomes active
		repayment_entry2.cancel()

		# Check only the demands related to repayment_entry1 are only cancelled
		loan_restructure = frappe.db.get_value(
			"Loan Restructure", {"loan_repayment": repayment_entry2.name}
		)
		loan_repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan_restructure": loan_restructure}
		)
		loan_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan_repayment_schedule": loan_repayment_schedule, "docstatus": 1},
		)
		self.assertFalse(loan_demands)

		# Check only the demands related to repayment_entry1 are only cancelled
		loan_restructure = frappe.db.get_value(
			"Loan Restructure", {"loan_repayment": repayment_entry1.name}
		)
		loan_repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan_restructure": loan_restructure}
		)
		loan_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan_repayment_schedule": loan_repayment_schedule, "docstatus": 1},
		)
		self.assertTrue(loan_demands)

	def test_future_demand_cancellation(self):
		loan = frappe.get_doc("Loan", self.loan)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(
			loan.name, "2024-06-04", 50287, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		demands = frappe.db.get_all(
			"Loan Demand", {"loan": loan.name, "docstatus": 2, "demand_date": (">", "2024-06-04")}
		)
		self.assertTrue(demands)
