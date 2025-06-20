import frappe
from frappe.utils import add_days, date_diff, now_datetime, nowdate

from erpnext.selling.doctype.customer.test_customer import get_customer_dict
from erpnext.setup.setup_wizard.operations.install_fixtures import set_global_defaults
from erpnext.setup.utils import enable_all_roles_and_domains

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)


def before_tests():
	frappe.clear_cache()
	# complete setup if missing
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = now_datetime().year

	if not frappe.get_list("Company"):
		setup_complete(
			{
				"currency": "INR",
				"full_name": "Test User",
				"company_name": "_Test Company",
				"timezone": "Asia/Kolkata",
				"company_abbr": "_TC",
				"industry": "Manufacturing",
				"country": "India",
				"fy_start_date": f"{year}-01-01",
				"fy_end_date": f"{year}-12-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@erpnext.com",
				"password": "test",
				"chart_of_accounts": "Standard",
			}
		)

	set_global_defaults(
		{
			"currency": "INR",
			"company_name": "_Test Company",
			"country": "India",
		}
	)

	enable_all_roles_and_domains()
	set_loan_settings_in_company()
	create_loan_accounts()
	setup_loan_demand_offset_order()
	set_loan_accrual_frequency("Monthly")

	frappe.db.commit()  # nosemgrep


def create_secured_demand_loan(applicant, disbursement_amount=None):
	pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

	loan_application = create_loan_application("_Test Company", applicant, "Demand Loan", pledge)
	create_loan_security_assignment(loan_application)

	loan = create_demand_loan(applicant, "Demand Loan", loan_application, posting_date="2019-10-01")
	loan.submit()

	first_date = "2019-10-01"
	last_date = "2019-10-30"

	make_loan_disbursement_entry(
		loan.name, disbursement_amount or loan.loan_amount, disbursement_date=first_date
	)
	process_loan_interest_accrual_for_loans(posting_date=last_date)

	return loan


def create_loan_scenario_for_penalty(doc):
	pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

	loan_application = create_loan_application("_Test Company", doc.applicant2, "Demand Loan", pledge)
	create_loan_security_assignment(loan_application)
	loan = create_demand_loan(
		doc.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
	)
	loan.submit()

	first_date = "2019-10-01"
	last_date = "2019-10-30"

	make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
	process_loan_interest_accrual_for_loans(posting_date=last_date)
	process_daily_loan_demands(posting_date=last_date, loan=loan.name)
	amounts = calculate_amounts(loan.name, add_days(last_date, 1))
	paid_amount = amounts["interest_amount"] / 2

	repayment_entry = create_repayment_entry(loan.name, add_days(last_date, 5), paid_amount)

	repayment_entry.submit()

	return loan, amounts


def create_loan_accounts():
	create_account(
		"Loans and Advances (Assets)",
		"Current Assets - _TC",
		"Asset",
		"",
		"Balance Sheet",
		is_group=1,
	)
	create_account("Loan Account", "Loans and Advances (Assets) - _TC", "Asset", "", "Balance Sheet")
	create_account("Payment Account", "Bank Accounts - _TC", "Asset", "Bank", "Balance Sheet")
	create_account("Disbursement Account", "Bank Accounts - _TC", "Asset", "Bank", "Balance Sheet")
	create_account(
		"Interest Income Account", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)

	create_account(
		"Interest Waiver Account",
		"Direct Expenses - _TC",
		"Expense",
		"Expense Account",
		"Profit and Loss",
	)

	create_account(
		"Penalty Waiver Account",
		"Direct Expenses - _TC",
		"Expense",
		"Expense Account",
		"Profit and Loss",
	)

	create_account(
		"Additional Interest Income Account",
		"Direct Income - _TC",
		"Income",
		"Income Account",
		"Profit and Loss",
	)

	create_account(
		"Additional Interest Accrued Account",
		"Current Assets - _TC",
		"Asset",
		"",
		"Balance Sheet",
	)

	create_account(
		"Additional Interest Waiver",
		"Direct Expenses - _TC",
		"Expense",
		"Expense Account",
		"Profit and Loss",
	)

	create_account(
		"Penalty Income Account", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)
	create_account(
		"Interest Receivable",
		"Accounts Receivable - _TC",
		"Asset",
		"Receivable",
		"Balance Sheet",
	)
	create_account(
		"Charges Receivable", "Accounts Receivable - _TC", "Asset", "Receivable", "Balance Sheet"
	)
	create_account(
		"Penalty Receivable", "Accounts Receivable - _TC", "Asset", "Receivable", "Balance Sheet"
	)

	create_account(
		"Additional Interest Receivable",
		"Accounts Receivable - _TC",
		"Asset",
		"Receivable",
		"Balance Sheet",
	)
	create_account(
		"Suspense Interest Receivable",
		"Accounts Receivable - _TC",
		"Asset",
		"Receivable",
		"Balance Sheet",
	)
	create_account(
		"Suspense Income Account", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)

	create_account(
		"Suspense Penalty Account", "Direct Income - _TC", "Income", "Income Account", "Profit and Loss"
	)

	create_account("Interest Accrued Account", "Current Assets - _TC", "Asset", "", "Balance Sheet")

	create_account(
		"Additional Interest Accrued Account",
		"Current Assets - _TC",
		"Asset",
		"",
		"Balance Sheet",
	)

	create_account(
		"Suspense Interest Accrued Account",
		"Current Assets - _TC",
		"Asset",
		"",
		"Balance Sheet",
	)

	create_account("Penalty Accrued Account", "Current Assets - _TC", "Asset", "", "Balance Sheet")

	create_account(
		"Broken Period Interest", "Accounts Receivable - _TC", "Asset", "Receivable", "Profit and Loss"
	)

	create_account(
		"Write Off Account", "Direct Expenses - _TC", "Expense", "Expense Account", "Profit and Loss"
	)

	create_account(
		"Write Off Recovery",
		"Loans and Advances (Assets) - _TC",
		"Liability",
		"Receivable",
		"Balance Sheet",
	)

	create_account(
		"Customer Refund Account",
		"Loans and Advances (Assets) - _TC",
		"Liability",
		"Receivable",
		"Balance Sheet",
	)

	create_account(
		"Processing Fee Income Account",
		"Direct Income - _TC",
		"Income",
		"Income Account",
		"Profit and Loss",
	)

	create_account(
		"Processing Fee Receivable Account",
		"Loans and Advances (Assets) - _TC",
		"Asset",
		"Receivable",
		"Balance Sheet",
	)

	create_account(
		"Processing Fee Waiver Account",
		"Direct Expenses - _TC",
		"Expense",
		"Expense Account",
		"Profit and Loss",
	)
	create_account(
		"Security Deposit Account",
		"Loans (Liabilities) - _TC",
		"Liability",
		"",
		"Balance Sheet",
	)


def create_account(account_name, parent_account, root_type, account_type, report_type, is_group=0):
	if not frappe.db.exists("Account", {"account_name": account_name}):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"company": "_Test Company",
				"root_type": root_type,
				"report_type": report_type,
				"currency": "INR",
				"parent_account": parent_account,
				"account_type": account_type,
				"is_group": is_group,
			}
		).insert(ignore_permissions=True)
	else:
		account = frappe.get_doc("Account", {"account_name": account_name})
		account.company = "_Test Company"
		account.root_type = root_type
		account.report_type = report_type
		account.account_currency = "INR"
		account.parent_account = parent_account
		account.account_type = account_type
		account.is_group = is_group

		account.save()


def create_loan_product(
	product_code,
	product_name,
	maximum_loan_amount,
	rate_of_interest,
	penalty_interest_rate=None,
	is_term_loan=1,
	grace_period_in_days=None,
	disbursement_account="Disbursement Account - _TC",
	payment_account="Payment Account - _TC",
	loan_account="Loan Account - _TC",
	interest_income_account="Interest Income Account - _TC",
	penalty_income_account="Penalty Income Account - _TC",
	penalty_waiver_account="Penalty Waiver Account - _TC",
	security_deposit_account="Security Deposit Account - _TC",
	write_off_recovery_account="Write Off Recovery - _TC",
	interest_receivable_account="Interest Receivable - _TC",
	penalty_receivable_account="Penalty Receivable - _TC",
	charges_receivable_account="Charges Receivable - _TC",
	suspense_interest_income="Suspense Income Account - _TC",
	interest_waiver_account="Interest Waiver Account - _TC",
	write_off_account="Write Off Account - _TC",
	customer_refund_account="Customer Refund Account - _TC",
	repayment_method=None,
	repayment_periods=None,
	repayment_schedule_type="Monthly as per repayment start date",
	repayment_date_on=None,
	days_past_due_threshold_for_npa=None,
	min_days_bw_disbursement_first_repayment=None,
	interest_accrued_account="Interest Accrued Account - _TC",
	penalty_accrued_account="Penalty Accrued Account - _TC",
	broken_period_interest_recovery_account="Broken Period Interest - _TC",
	additional_interest_income="Additional Interest Income Account - _TC",
	additional_interest_accrued="Additional Interest Accrued Account - _TC",
	additional_interest_receivable="Additional Interest Receivable - _TC",
	additional_interest_waiver="Additional Interest Waiver - _TC",
	cyclic_day_of_the_month=5,
	collection_offset_sequence_for_standard_asset=None,
	collection_offset_sequence_for_sub_standard_asset=None,
	collection_offset_sequence_for_written_off_asset=None,
	collection_offset_sequence_for_settlement_collection=None,
):

	loan_product = frappe.get_all("Loan Product", filters={"product_name": product_name}, limit=1)
	if loan_product:
		loan_product_doc = frappe.get_doc("Loan Product", loan_product[0].name)
	else:
		loan_product_doc = frappe.new_doc("Loan Product")

	loan_product_doc.company = "_Test Company"
	loan_product_doc.product_code = product_code
	loan_product_doc.product_name = product_name
	loan_product_doc.is_term_loan = is_term_loan
	loan_product_doc.repayment_schedule_type = repayment_schedule_type
	loan_product_doc.cyclic_day_of_the_month = cyclic_day_of_the_month
	loan_product_doc.maximum_loan_amount = maximum_loan_amount
	loan_product_doc.rate_of_interest = rate_of_interest
	loan_product_doc.penalty_interest_rate = penalty_interest_rate
	loan_product_doc.grace_period_in_days = grace_period_in_days
	loan_product_doc.disbursement_account = disbursement_account
	loan_product_doc.payment_account = payment_account
	loan_product_doc.loan_account = loan_account
	loan_product_doc.interest_income_account = interest_income_account
	loan_product_doc.penalty_income_account = penalty_income_account
	loan_product_doc.penalty_waiver_account = penalty_waiver_account
	loan_product_doc.security_deposit_account = security_deposit_account
	loan_product_doc.write_off_recovery_account = write_off_recovery_account
	loan_product_doc.interest_receivable_account = interest_receivable_account
	loan_product_doc.penalty_receivable_account = penalty_receivable_account
	loan_product_doc.charges_receivable_account = charges_receivable_account
	loan_product_doc.suspense_interest_income = suspense_interest_income
	loan_product_doc.interest_waiver_account = interest_waiver_account
	loan_product_doc.interest_accrued_account = interest_accrued_account
	loan_product_doc.penalty_accrued_account = penalty_accrued_account
	loan_product_doc.write_off_account = write_off_account
	loan_product_doc.broken_period_interest_recovery_account = broken_period_interest_recovery_account
	loan_product_doc.additional_interest_income = additional_interest_income
	loan_product_doc.additional_interest_accrued = additional_interest_accrued
	loan_product_doc.additional_interest_receivable = additional_interest_receivable
	loan_product_doc.additional_interest_waiver = additional_interest_waiver
	loan_product_doc.customer_refund_account = customer_refund_account
	loan_product_doc.repayment_method = repayment_method
	loan_product_doc.repayment_periods = repayment_periods
	loan_product_doc.write_off_amount = 100
	loan_product_doc.days_past_due_threshold_for_npa = days_past_due_threshold_for_npa
	loan_product_doc.min_days_bw_disbursement_first_repayment = (
		min_days_bw_disbursement_first_repayment
	)
	loan_product_doc.min_auto_closure_tolerance_amount = -100
	loan_product_doc.max_auto_closure_tolerance_amount = 100
	loan_product_doc.collection_offset_sequence_for_standard_asset = (
		collection_offset_sequence_for_standard_asset
	)
	loan_product_doc.collection_offset_sequence_for_sub_standard_asset = (
		collection_offset_sequence_for_sub_standard_asset
	)
	loan_product_doc.collection_offset_sequence_for_written_off_asset = (
		collection_offset_sequence_for_written_off_asset
	)
	loan_product_doc.collection_offset_sequence_for_settlement_collection = (
		collection_offset_sequence_for_settlement_collection
	)

	if loan_product_doc.is_term_loan:
		loan_product_doc.repayment_schedule_type = repayment_schedule_type
		if loan_product_doc.repayment_schedule_type != "Monthly as per repayment start date":
			loan_product_doc.repayment_date_on = repayment_date_on

	loan_product_doc.save()

	return loan_product_doc


def add_or_update_loan_charges(product_name):
	loan_product = frappe.get_doc("Loan Product", product_name)

	charge_type = "Processing Fee"

	if not frappe.db.exists("Item", charge_type):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": charge_type,
				"item_group": "Services",
				"is_stock_item": 0,
				"income_account": "Processing Fee Income Account - _TC",
			}
		).insert()

	loan_product.loan_charges = []

	loan_product.append(
		"loan_charges",
		{
			"charge_type": charge_type,
			"income_account": "Processing Fee Income Account - _TC",
			"receivable_account": "Processing Fee Receivable Account - _TC",
			"waiver_account": "Processing Fee Waiver Account - _TC",
		},
	)
	loan_product.save()


def create_loan_security_type():
	if not frappe.db.exists("Loan Security Type", "Stock"):
		frappe.get_doc(
			{
				"doctype": "Loan Security Type",
				"loan_security_type": "Stock",
				"unit_of_measure": "Nos",
				"haircut": 50.00,
				"loan_to_value_ratio": 50,
			}
		).insert(ignore_permissions=True)


def create_loan_security():
	if not frappe.db.exists("Loan Security", "Test Security 1"):
		frappe.get_doc(
			{
				"doctype": "Loan Security",
				"loan_security_type": "Stock",
				"loan_security_code": "Test Security 1",
				"loan_security_name": "Test Security 1",
				"unit_of_measure": "Nos",
				"haircut": 50.00,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Loan Security", "Test Security 2"):
		frappe.get_doc(
			{
				"doctype": "Loan Security",
				"loan_security_type": "Stock",
				"loan_security_code": "Test Security 2",
				"loan_security_name": "Test Security 2",
				"unit_of_measure": "Nos",
				"haircut": 50.00,
			}
		).insert(ignore_permissions=True)


def make_loan_disbursement_entry(
	loan,
	amount,
	disbursement_date=None,
	repayment_start_date=None,
	repayment_frequency=None,
	withhold_security_deposit=False,
	loan_disbursement_charges=None,
):
	loan_disbursement_entry = frappe.new_doc("Loan Disbursement")
	loan_disbursement_entry.against_loan = loan
	loan_disbursement_entry.disbursement_date = disbursement_date or nowdate()
	loan_disbursement_entry.repayment_start_date = (
		repayment_start_date or disbursement_date or nowdate()
	)
	loan_disbursement_entry.repayment_frequency = repayment_frequency
	loan_disbursement_entry.company = "_Test Company"
	loan_disbursement_entry.disbursed_amount = amount
	loan_disbursement_entry.cost_center = "Main - _TC"
	loan_disbursement_entry.withhold_security_deposit = withhold_security_deposit

	if loan_disbursement_charges:
		for charge in loan_disbursement_charges:
			loan_disbursement_entry.append(
				"loan_disbursement_charges",
				{
					"charge": charge.get("charge"),
					"amount": charge.get("amount"),
				},
			)

	loan_disbursement_entry.save()
	loan_disbursement_entry.submit()

	return loan_disbursement_entry


def create_loan_security_price(loan_security, loan_security_price, uom, from_date, to_date):
	if not frappe.db.get_value(
		"Loan Security Price",
		{"loan_security": loan_security, "valid_from": ("<=", from_date), "valid_upto": (">=", to_date)},
		"name",
	):

		lsp = frappe.get_doc(
			{
				"doctype": "Loan Security Price",
				"loan_security": loan_security,
				"loan_security_price": loan_security_price,
				"uom": uom,
				"valid_from": from_date,
				"valid_upto": to_date,
			}
		).insert(ignore_permissions=True)


def create_repayment_entry(
	loan,
	value_date,
	paid_amount,
	repayment_type="Normal Repayment",
	loan_disbursement=None,
	payable_charges=None,
):
	lr = frappe.new_doc("Loan Repayment")
	lr.against_loan = loan
	lr.company = "_Test Company"
	lr.posting_date = nowdate()
	lr.value_date = value_date
	lr.amount_paid = paid_amount
	lr.repayment_type = repayment_type
	lr.loan_disbursement = loan_disbursement

	if payable_charges:
		for charge in payable_charges:
			lr.append("payable_charges", charge)

	lr.insert(ignore_permissions=True)

	return lr


def create_loan_application(
	company,
	applicant,
	loan_product,
	proposed_pledges,
	repayment_method=None,
	repayment_periods=None,
	posting_date=None,
	do_not_save=False,
):
	loan_application = frappe.new_doc("Loan Application")
	loan_application.applicant_type = "Customer"
	loan_application.company = company
	loan_application.applicant = applicant
	loan_application.loan_product = loan_product
	loan_application.posting_date = posting_date or nowdate()
	loan_application.is_secured_loan = 1

	if repayment_method:
		loan_application.repayment_method = repayment_method
		loan_application.repayment_periods = repayment_periods

	for pledge in proposed_pledges:
		loan_application.append("proposed_pledges", pledge)

	if do_not_save:
		return loan_application

	loan_application.save()
	loan_application.submit()

	loan_application.status = "Approved"
	loan_application.save()

	return loan_application.name


def create_loan(
	applicant,
	loan_product,
	loan_amount,
	repayment_method,
	repayment_periods=None,
	applicant_type=None,
	repayment_start_date=None,
	posting_date=None,
	monthly_repayment_amount=None,
	rate_of_interest=None,
	limit_applicable_start=None,
	limit_applicable_end=None,
	loan_partner=None,
	moratorium_tenure=None,
	moratorium_type=None,
	penalty_charges_rate=None,
	repayment_frequency=None,
):

	loan = frappe.get_doc(
		{
			"doctype": "Loan",
			"applicant_type": "Customer",
			"company": "_Test Company",
			"applicant": applicant,
			"loan_product": loan_product,
			"loan_amount": loan_amount,
			"maximum_limit_amount": loan_amount,
			"repayment_method": repayment_method,
			"repayment_periods": repayment_periods,
			"monthly_repayment_amount": monthly_repayment_amount,
			"repayment_start_date": repayment_start_date or nowdate(),
			"posting_date": posting_date or nowdate(),
			"rate_of_interest": rate_of_interest,
			"limit_applicable_start": limit_applicable_start,
			"limit_applicable_end": limit_applicable_end,
			"loan_partner": loan_partner,
			"moratorium_tenure": moratorium_tenure,
			"moratorium_type": moratorium_type,
			"penalty_charges_rate": penalty_charges_rate,
			"repayment_frequency": repayment_frequency or "Monthly",
		}
	)

	loan.save()
	return loan


def create_loan_with_security(
	applicant,
	loan_product,
	repayment_method,
	repayment_periods,
	loan_application,
	posting_date=None,
	repayment_start_date=None,
):
	loan = frappe.get_doc(
		{
			"doctype": "Loan",
			"company": "_Test Company",
			"applicant_type": "Customer",
			"posting_date": posting_date or nowdate(),
			"loan_application": loan_application,
			"applicant": applicant,
			"loan_product": loan_product,
			"is_term_loan": 1,
			"is_secured_loan": 1,
			"repayment_method": repayment_method,
			"repayment_periods": repayment_periods,
			"repayment_start_date": repayment_start_date or nowdate(),
			"payment_account": "Payment Account - _TC",
			"loan_account": "Loan Account - _TC",
			"interest_income_account": "Interest Income Account - _TC",
			"penalty_income_account": "Penalty Income Account - _TC",
		}
	)

	loan.save()

	return loan


def create_demand_loan(applicant, loan_product, loan_application, posting_date=None):
	loan = frappe.new_doc("Loan")
	loan.company = "_Test Company"
	loan.applicant_type = "Customer"
	loan.applicant = applicant
	loan.loan_product = loan_product
	loan.posting_date = posting_date or nowdate()
	loan.loan_application = loan_application
	loan.is_term_loan = 0
	loan.is_secured_loan = 1
	loan.payment_account = "Payment Account - _TC"
	loan.loan_account = "Loan Account - _TC"
	loan.interest_income_account = "Interest Income Account - _TC"
	loan.penalty_income_account = "Penalty Income Account - _TC"

	loan.save()

	return loan


def create_loan_partner(
	partner_code,
	partner_name,
	partner_loan_share_percentage,
	effective_date,
	fldg_fixed_deposit_percentage,
	partial_payment_mechanism=None,
	repayment_schedule_type="EMI (PMT) based",
	partner_base_interest_rate=10.0,
	enable_partner_accounting=0,
	organization_type="Centralized",
	fldg_trigger_dpd=None,
	fldg_limit_calculation_component="Disbursement",
	type_of_fldg_applicable="Fixed Deposit Only",
	servicer_fee=False,
	restructure_of_loans_applicable=False,
	waiving_of_charges_applicable=False,
):
	partner = frappe.get_doc(
		{
			"doctype": "Loan Partner",
			"partner_code": "Test Loan Partner 1",
			"partner_name": "Test Loan Partner 1",
			"partner_loan_share_percentage": partner_loan_share_percentage,
			"partial_payment_mechanism": partial_payment_mechanism,
			"repayment_schedule_type": repayment_schedule_type,
			"effective_date": effective_date or nowdate(),
			"partner_base_interest_rate": partner_base_interest_rate,
			"enable_partner_accounting": enable_partner_accounting,
			"organization_type": organization_type,
			"fldg_trigger_dpd": fldg_trigger_dpd,
			"fldg_limit_calculation_component": fldg_limit_calculation_component,
			"type_of_fldg_applicable": type_of_fldg_applicable,
			"servicer_fee": servicer_fee,
			"restructure_of_loans_applicable": restructure_of_loans_applicable,
			"waiving_of_charges_applicable": waiving_of_charges_applicable,
			"fldg_fixed_deposit_percentage": fldg_fixed_deposit_percentage,
		}
	)

	partner.insert()
	return partner


def set_loan_settings_in_company(company=None):
	if not company:
		company = "_Test Company"
	company = frappe.get_doc("Company", company)
	company.min_days_bw_disbursement_first_repayment = 15
	company.save()


def setup_loan_demand_offset_order(company=None):
	if not company:
		company = "_Test Company"

	create_demand_offset_order(
		"Test Demand Loan Loan Demand Offset Order", ["Penalty", "Interest", "Principal"]
	)
	create_demand_offset_order(
		"Test EMI Based Standard Loan Demand Offset Order",
		["EMI (Principal + Interest)", "Penalty", "Charges"],
	)

	create_demand_offset_order(
		"Test Standard Loan Demand Offset Order",
		["EMI (Principal + Interest)", "Additional Interest", "Penalty", "Charges"],
	)

	doc = frappe.get_doc("Company", company)
	if not doc.get("collection_offset_sequence_for_standard_asset"):
		doc.collection_offset_sequence_for_standard_asset = (
			"Test EMI Based Standard Loan Demand Offset Order"
		)

	if not doc.get("collection_offset_sequence_for_sub_standard_asset"):
		doc.collection_offset_sequence_for_sub_standard_asset = (
			"Test EMI Based Standard Loan Demand Offset Order"
		)

	if not doc.get("collection_offset_sequence_for_written_off_asset"):
		doc.collection_offset_sequence_for_written_off_asset = (
			"Test Demand Loan Loan Demand Offset Order"
		)

	if not doc.get("collection_offset_sequence_for_settlement_collection"):
		doc.collection_offset_sequence_for_settlement_collection = (
			"Test Demand Loan Loan Demand Offset Order"
		)

	doc.save()


def create_demand_offset_order(order_name, components):
	if not frappe.db.get_value("Loan Demand Offset Order", {"title": order_name}):
		order = frappe.new_doc("Loan Demand Offset Order")
		order.title = order_name

		for component in components:
			order.append("components", {"demand_type": component})

		order.insert()


def create_loan_write_off(loan, posting_date, write_off_amount=None):
	loan_write_off = frappe.new_doc("Loan Write Off")
	loan_write_off.loan = loan
	loan_write_off.value_date = posting_date
	loan_write_off.company = "_Test Company"
	loan_write_off.write_off_account = "Write Off Account - _TC"
	loan_write_off.save()
	loan_write_off.submit()

	return loan_write_off


def set_loan_accrual_frequency(loan_accrual_frequency):
	frappe.db.set_value(
		"Company",
		"_Test Company",
		"loan_accrual_frequency",
		loan_accrual_frequency,
	)


def get_loan_interest_accrual(loan, from_date, to_date):
	loan_interest_accruals = frappe.db.get_all(
		"Loan Interest Accrual",
		{"loan": loan, "docstatus": 1, "posting_date": ("between", [from_date, to_date])},
		pluck="posting_date",
		order_by="posting_date",
	)
	return loan_interest_accruals


def master_init():
	set_loan_settings_in_company()
	create_loan_accounts()
	setup_loan_demand_offset_order()
	set_loan_accrual_frequency("Weekly")


def init_loan_products():
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

	for loan_product in simple_terms_loans:
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

	for loan_product in loc_loans:
		create_loan_product(
			loan_product[0],
			loan_product[0],
			loan_product[1],
			loan_product[2],
			repayment_schedule_type=loan_product[3],
		)

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


def init_customers():
	make_customer("_Test Loan Customer")

	make_customer("_Test Loan Customer 1")


def make_customer(customer_name):
	if not frappe.db.exists("Customer", customer_name):
		frappe.get_doc(get_customer_dict(customer_name)).insert(ignore_permissions=True)


def get_penalty_amount(penalty_date, emi_date, pending_amount, penalty_rate):
	no_of_days = date_diff(penalty_date, emi_date)
	penal_interest = (pending_amount * no_of_days * penalty_rate) / 36500

	return penal_interest


def create_loan_refund(
	loan, posting_date, refund_amount, is_excess_amount_refund=0, is_security_amount_refund=0
):
	doc = frappe.new_doc("Loan Refund")
	doc.loan = loan
	doc.value_date = posting_date
	doc.company = "_Test Company"
	doc.is_excess_amount_refund = is_excess_amount_refund
	doc.is_security_amount_refund = is_security_amount_refund
	doc.refund_amount = refund_amount
	doc.refund_account = "Payment Account - _TC"
	doc.save()
	doc.submit()

	return doc
