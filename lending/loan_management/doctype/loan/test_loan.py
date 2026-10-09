# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import add_days, add_months, date_diff, flt, get_datetime, getdate, nowdate

from erpnext.selling.doctype.customer.test_customer import get_customer_dict

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
	add_or_update_loan_charges,
	create_demand_loan,
	create_loan,
	create_loan_accounts,
	create_loan_application,
	create_loan_partner,
	create_loan_product,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_with_security,
	create_repayment_entry,
	create_secured_demand_loan,
	loan_classification_ranges,
	make_loan_disbursement_entry,
	set_loan_accrual_frequency,
	set_loan_settings_in_company,
	setup_loan_demand_offset_order,
)
from lending.tests.utils import LendingTestSuite


class TestLoan(LendingTestSuite):
	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()
		loan_classification_ranges()

		set_loan_accrual_frequency("Monthly")
		simple_terms_loans = [
			["Personal Loan", 500000, 8.4, "Monthly as per repayment start date"],
			["Term Loan Product 1", 12000, 7.5, "Monthly as per repayment start date"],
		]

		pro_rated_term_loans = [
			["Term Loan Product 2", 12000, 7.5, "Pro-rated calendar months", "Start of the next month"],
			["Term Loan Product 3", 1200, 25, "Pro-rated calendar months", "End of the current month"],
		]

		cyclic_date_term_loans = [
			["Term Loan Product 4", 3000000, 25, "Monthly as per cycle date"],
		]

		loc_loans = [
			["Term Loan Product 5", 3000000, 25, "Line of Credit"],
		]

		flat_interest_rate_loans = [
			["Flat Interest Rate Loan", 1000000, 12, "Flat Interest Rate"],
		]

		for loan_product in simple_terms_loans + flat_interest_rate_loans + loc_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)

		for loan_product in cyclic_date_term_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)
			add_or_update_loan_charges(loan_product[0])

		for loan_product in pro_rated_term_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
				repayment_date_on=loan_product[4],
			)

		create_loan_product(
			"Stock Loan",
			"Stock Loan",
			2000000,
			13.5,
			25,
			1,
			5,
			repayment_schedule_type="Monthly as per repayment start date",
			collection_offset_sequence_for_standard_asset="Test EMI Based Standard Loan Demand Offset Order",
		)

		create_loan_product(
			"Demand Loan",
			"Demand Loan",
			2000000,
			13.5,
			25,
			0,
			5,
			collection_offset_sequence_for_standard_asset="Test Demand Loan Loan Demand Offset Order",
			collection_offset_sequence_for_sub_standard_asset=None,
			collection_offset_sequence_for_written_off_asset=None,
			collection_offset_sequence_for_settlement_collection=None,
		)

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
		create_loan_security_price("Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)

		if not frappe.db.exists("Customer", "_Test Loan Customer"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer")).insert(ignore_permissions=True)

		if not frappe.db.exists("Customer", "_Test Loan Customer 1"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer 1")).insert(ignore_permissions=True)

		if not frappe.db.exists("Customer", "_Test Loan Customer 2"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer 2")).insert(ignore_permissions=True)

		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		self.applicant3 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer 1"}, "name")
		self.applicant1 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer 2"}, "name")

		frappe.db.set_value(
			"Loan Product", "Demand Loan", "customer_refund_account", "Customer Refund Account - _TC"
		)

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
			repayment_start_date=add_months(disbursement_date, 1),
		)

		loan.repayment_method = "Repay Fixed Amount per Period"
		loan.monthly_repayment_amount = 14000
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

	def test_sanctioned_amount_tolerance(self):
		frappe.db.sql("DELETE FROM `tabLoan` where applicant = '_Test Loan Customer 1'")
		frappe.db.sql("DELETE FROM `tabLoan Application` where applicant = '_Test Loan Customer 1'")
		frappe.db.sql(
			"DELETE FROM `tabLoan Security Assignment` where applicant = '_Test Loan Customer 1'"
		)
		frappe.db.delete(
			"Sanctioned Loan Amount",
			{"applicant": "_Test Loan Customer 1", "company": "_Test Company"},
		)

		create_loan_security_assignment(
			applicant_type="Customer",
			applicant=self.applicant3,
			company="_Test Company",
			securities=[{"loan_security": "Test Security 1", "qty": 4000.00}],
		)

		sanctioned_amount_limit = frappe.db.get_value(
			"Sanctioned Loan Amount",
			{"applicant": "_Test Loan Customer 1", "company": "_Test Company"},
			"sanctioned_amount_limit",
		)
		self.assertEqual(sanctioned_amount_limit, 1000000)

		# 0.01% tolerance on a 1,000,000 limit -> allowed limit of 1,000,100
		frappe.db.set_value(
			"Loan Product", "Demand Loan", "sanctioned_amount_tolerance_percentage", 0.01
		)

		# qty 4000.4 * price 500 * (1 - 50% haircut) = 1,000,100, exactly limit + tolerance -> allowed
		at_tolerance_pledge = [{"loan_security": "Test Security 1", "qty": 4000.40}]
		loan_application = create_loan_application(
			"_Test Company", self.applicant3, "Demand Loan", at_tolerance_pledge
		)
		self.assertTrue(frappe.db.exists("Loan Application", loan_application))

		frappe.db.delete("Loan Application", {"applicant": "_Test Loan Customer 1"})

		# qty 4000.8 * price 500 * (1 - 50% haircut) = 1,000,200, beyond limit + tolerance -> rejected
		beyond_tolerance_pledge = [{"loan_security": "Test Security 1", "qty": 4000.80}]
		loan_application = create_loan_application(
			"_Test Company", self.applicant3, "Demand Loan", beyond_tolerance_pledge, do_not_save=True
		)
		self.assertRaises(frappe.ValidationError, loan_application.save)

		frappe.db.set_value("Loan Product", "Demand Loan", "sanctioned_amount_tolerance_percentage", 0)

	def test_loan_closure(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

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

	def test_loan_security_release(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

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
		process_loan_interest_accrual_for_loans(posting_date=last_date, company="_Test Company")

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

	def test_sanctioned_loan_security_release(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		unpledge_map = {"Test Security 1": 4000}
		unpledge_request = unpledge_security(loan=loan.name, security_map=unpledge_map, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		unpledge_request.submit()

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

	def test_pending_loan_amount_after_closure_request(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

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

	def test_penalty_and_auto_create_disbursement_with_charges(self):
		frappe.db.set_value("Company", "_Test Company", "enable_loan_accounting", 0)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-01",
			penalty_charges_rate=25,
			auto_create_disbursement_on_loan_booking=1,
			disbursement_charges=[
				{
					"charge": "Processing Fee",
					"amount": 100,
					"treatment_of_charge": "Add to first repayment"
				}
			]
		)

		loan.submit()

		charge_demand = frappe.db.get_value("Loan Demand", {"loan": loan.name, "demand_type": "Charges"}, "name")
		self.assertTrue(charge_demand)

		process_daily_loan_demands(posting_date="2024-07-06", loan=loan.name)
		process_loan_interest_accrual_for_loans(
			posting_date="2024-07-06", loan=loan.name, company="_Test Company"
		)

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-07-06")
		self.assertEqual(flt(amounts["penalty_amount"], 2), 3055.36)

		frappe.db.set_value("Company", "_Test Company", "enable_loan_accounting", 0)

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

	def test_multiple_advance_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
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
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
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

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(
			loan.name, "2024-06-04", 50287, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		demands = frappe.db.get_all(
			"Loan Demand", {"loan": loan.name, "docstatus": 2, "demand_date": (">", "2024-06-04")}
		)
		self.assertTrue(demands)

	def test_advance_payment_then_prepayment(self):
		# Purpose: check that an EMI skipped by an Advance Payment stays skipped even
		# after more Pre Payments are made later. Without this, the skipped EMI can
		# wrongly come back as due again, even though the customer already paid for it.
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2025-01-05",
			posting_date="2024-12-05",
			rate_of_interest=10,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-12-05", repayment_start_date="2025-01-05"
		)
		process_daily_loan_demands(posting_date="2025-01-05", loan=loan.name)
		create_repayment_entry(loan.name, "2025-02-01", 8792.00).submit()
		create_repayment_entry(loan.name, "2025-02-01", 10000, repayment_type="Advance Payment").submit()

		active_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "status": "Active", "docstatus": 1}, "name"
		)
		demand_generated = frappe.db.get_value(
			"Repayment Schedule", {"parent": active_schedule, "payment_date": "2025-02-05"}, "demand_generated"
		)
		self.assertEqual(demand_generated, 1)

		create_repayment_entry(loan.name, "2025-02-01", 20000, repayment_type="Pre Payment").submit()

		active_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "status": "Active", "docstatus": 1}, "name"
		)
		demand_generated = frappe.db.get_value(
			"Repayment Schedule", {"parent": active_schedule, "payment_date": "2025-02-05"}, "demand_generated"
		)
		self.assertEqual(demand_generated, 1)

		live_demands = frappe.db.get_all(
			"Loan Demand",
			{
				"loan": loan.name,
				"docstatus": 1,
				"demand_date": "2025-02-05",
				"demand_type": "EMI",
			},
		)
		self.assertFalse(live_demands)

		create_repayment_entry(loan.name, "2025-02-04", 15000, repayment_type="Pre Payment").submit()

		active_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan": loan.name, "status": "Active", "docstatus": 1}, "name"
		)
		demand_generated = frappe.db.get_value(
			"Repayment Schedule", {"parent": active_schedule, "payment_date": "2025-02-05"}, "demand_generated"
		)
		self.assertEqual(demand_generated, 1)

		live_demands = frappe.db.get_all(
			"Loan Demand",
			{
				"loan": loan.name,
				"docstatus": 1,
				"demand_date": "2025-02-05",
				"demand_type": "EMI",
			},
		)
		self.assertFalse(live_demands)

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

	def test_loan_cancellation_post_disbursement(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2000000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-08-05",
			posting_date="2024-07-05",
			rate_of_interest=22,
			applicant_type="Customer",
		)

		loan.submit()

		loan_disbursement = make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-07-05", repayment_start_date="2024-08-05"
		)

		process_daily_loan_demands(posting_date="2024-09-05", loan=loan.name)

		# self.assertRaises(frappe.exceptions.LinkExistsError, loan.cancel)

		loan_disbursement.load_from_db()
		self.assertTrue(loan_disbursement.cancel())
		loan.load_from_db()
		self.assertTrue(loan.cancel())

	def test_partial_settlement_extra_amount_not_added_to_principal(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			200000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			posting_date="2024-07-05",
			repayment_start_date="2024-08-05",
			rate_of_interest=22,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-07-05", repayment_start_date="2024-08-05"
		)
		process_daily_loan_demands(posting_date="2024-08-05", loan=loan.name)

		# Pay exactly the currently-due principal plus a small overshoot as a
		# Partial Settlement, with interest left unpaid.
		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-08-05")
		overshoot = 2000
		pay_amount = flt(amounts["payable_principal_amount"] + overshoot, 2)
		rep = create_repayment_entry(loan.name, "2024-08-05", pay_amount, repayment_type="Partial Settlement")
		rep.submit()

		# principal_amount_paid must be fully backed by repayment_details
		# allocation rows - the overshoot must not be silently folded into
		# principal_amount_paid, and no leftover should have been booked as a
		# new, separately-created Principal demand.
		allocated_principal = sum(
			d.paid_amount
			for d in frappe.db.get_all(
				"Loan Repayment Detail",
				{"parent": rep.name, "demand_subtype": "Principal"},
				["paid_amount"],
			)
		)
		self.assertEqual(flt(rep.principal_amount_paid), flt(allocated_principal))

		new_principal_demands = frappe.db.get_all(
			"Loan Demand",
			{
				"loan": loan.name,
				"loan_repayment": rep.name,
				"demand_type": "EMI",
				"demand_subtype": "Principal",
				"docstatus": 1,
			},
		)
		self.assertEqual(
			new_principal_demands,
			[],
			"Partial Settlement should not create a new Principal demand for its overshoot",
		)
