# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, flt, nowdate

from lending.loan_management.doctype.loan.loan import unpledge_security
from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
	get_total_pledged_security_value,
)
from lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall import (
	create_process_loan_security_shortfall,
)
from lending.tests.test_utils import (
	create_loan,
	create_loan_application,
	create_loan_product,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_with_security,
	make_customer,
	make_loan_disbursement_entry,
	master_init,
)
from lending.tests.utils import LendingTestSuite

APPLICANT = "_Test Gold Loan Customer"
CONSUMPTION_PRODUCT = "Gold Consumption Loan"
INCOME_PRODUCT = "Gold Business Loan"
RBI_SLABS = [
	{"up_to_amount": 250000, "ltv": 85},
	{"up_to_amount": 500000, "ltv": 80},
	{"up_to_amount": 0, "ltv": 75},
]

# Meena's necklace and bangles: 41.651 g of Gold 916 at ₹9,000, a value of ₹3,74,859
MEENA_PLEDGE = [{"loan_security": "Gold 916", "qty": 41.651, "haircut": 15}]


class TestGoldLoanLTV(LendingTestSuite):
	def setUp(self):
		master_init()
		make_customer(APPLICANT)
		create_loan_security_type()
		create_loan_security()
		setup_gold_securities()
		setup_gold_products()
		frappe.db.set_single_value("Lending Settings", "gold_credit_assessment_above", 0)

	def test_slab_limit_for_a_new_borrower(self):
		application = make_application(MEENA_PLEDGE)

		self.assertEqual(application.maximum_loan_amount, 299887)
		self.assertAlmostEqual(flt(application.proposed_pledges[0].haircut), 20, places=2)

		loan = make_loan(application.name)
		self.assertEqual(flt(loan.gold_ltv_cap), 80)

	def test_lower_value_stays_in_the_first_slab(self):
		# ₹3,00,000 at 80% is only ₹2,40,000, so the 85% slab capped at ₹2,50,000 lends more
		application = make_application([{"loan_security": "Gold 999", "qty": 30, "haircut": 15}])

		self.assertEqual(application.maximum_loan_amount, 250000)
		self.assertEqual(flt(make_loan(application.name).gold_ltv_cap), 85)

	def test_slab_counts_the_borrowers_other_loans(self):
		first = make_application([{"loan_security": "Gold 916", "qty": 30, "haircut": 15}], loan_amount=200000)
		make_loan(first.name).submit()

		second = make_application([{"loan_security": "Gold 999", "qty": 10, "haircut": 15}])

		# ₹50,000 more fits the 85% slab; ₹80,000 fits the 80% slab at a total of ₹2,80,000
		self.assertEqual(second.maximum_loan_amount, 80000)
		self.assertEqual(flt(make_loan(second.name).gold_ltv_cap), 80)

	def test_share_lines_keep_their_haircut(self):
		pledges = MEENA_PLEDGE + [{"loan_security": "Test Security 1", "qty": 100, "haircut": 50}]
		create_loan_security_price(
			"Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
		)
		application = make_application(pledges)

		gold, shares = application.proposed_pledges
		self.assertAlmostEqual(flt(gold.haircut), 20, places=2)
		self.assertEqual(flt(shares.haircut), 50)
		self.assertEqual(application.maximum_loan_amount, 299887 + 25000)

	def test_share_lending_counts_toward_the_gold_slab(self):
		create_loan_security_price(
			"Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
		)
		# ₹3,00,000 of gold alone gets ₹2,50,000 at 85%. With ₹50,000 against shares the total
		# passes ₹2,50,000, so the gold must fit the 80% slab: ₹2,40,000
		pledges = [
			{"loan_security": "Gold 999", "qty": 30, "haircut": 15},
			{"loan_security": "Test Security 1", "qty": 200, "haircut": 50},
		]
		application = make_application(pledges)

		self.assertEqual(application.maximum_loan_amount, 290000)
		self.assertAlmostEqual(flt(application.proposed_pledges[0].haircut), 20, places=2)

		loan = make_loan(application.name)
		loan.submit()
		self.assertEqual(flt(loan.gold_ltv_cap), 80)

		make_loan_disbursement_entry(loan.name, loan.loan_amount)
		create_process_loan_security_shortfall()
		self.assertFalse(frappe.db.exists("Loan Security Shortfall", {"loan": loan.name}))

	def test_products_without_slabs_keep_the_security_haircut(self):
		for product in (INCOME_PRODUCT, "Gold Consumption Loan No Slabs"):
			application = make_application(MEENA_PLEDGE, loan_product=product)

			self.assertEqual(flt(application.proposed_pledges[0].haircut), 15)
			self.assertEqual(application.maximum_loan_amount, 318630)
			self.assertFalse(flt(make_loan(application.name, loan_product=product).gold_ltv_cap))

	def test_shortfall_uses_the_slab_cap(self):
		loan = make_disbursed_meena_loan()

		# At ₹8,550 the gold is worth ₹3,56,116: 85% covers ₹2,99,887, the 80% cap does not
		set_gold_price("Gold 916", 8550)
		create_process_loan_security_shortfall()

		shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})
		self.assertEqual(flt(shortfall.shortfall_amount), flt(299887 - 41.651 * 8550 * 0.8, 2))

	def test_release_uses_the_slab_cap(self):
		loan = make_disbursed_meena_loan()

		# 40.651 g left is worth ₹3,65,859: 85% covers ₹2,99,887, the 80% cap does not
		with self.assertRaises(frappe.ValidationError):
			unpledge_security(loan=loan.name, security_map={"Gold 916": 1}, save=1)

	def test_current_price_limit_uses_the_slab_cap(self):
		loan = make_disbursed_meena_loan()

		self.assertEqual(flt(get_total_pledged_security_value(loan.name), 2), flt(374859 * 0.8, 2))

	def test_gold_needs_a_loan_or_application(self):
		with self.assertRaises(frappe.ValidationError):
			create_loan_security_assignment(
				securities=[{"loan_security": "Gold 916", "qty": 10}],
				applicant_type="Customer",
				applicant=APPLICANT,
				company="_Test Company",
			)

	def test_credit_assessment_above_threshold(self):
		frappe.db.set_single_value("Lending Settings", "gold_credit_assessment_above", 250000)

		with self.assertRaises(frappe.ValidationError):
			make_application(MEENA_PLEDGE)

		application = make_application(MEENA_PLEDGE, credit_assessment="/files/assessment.pdf")
		self.assertEqual(application.maximum_loan_amount, 299887)

	def test_pledge_against_a_loan_made_without_collateral(self):
		loan = create_loan(APPLICANT, CONSUMPTION_PRODUCT, 299887, "Repay Over Number of Periods", 12)
		self.assertEqual(flt(loan.gold_ltv_cap), 80)

		assignment = frappe.get_doc(
			"Loan Security Assignment",
			create_loan_security_assignment(loan=loan.name, securities=[dict(MEENA_PLEDGE[0])]),
		)
		self.assertAlmostEqual(flt(assignment.securities[0].haircut), 20, places=2)
		self.assertEqual(assignment.maximum_loan_value, 299887)

	def test_applicant_wise_value_uses_the_slab_cap(self):
		make_disbursed_meena_loan()

		value = get_total_pledged_security_value(applicant=APPLICANT, on_shortfall_check=True)
		self.assertEqual(flt(value, 2), flt(374859 * 0.8, 2))

	def test_security_haircut_above_the_slab_is_kept(self):
		frappe.db.set_value("Loan Security", "Gold 916", "haircut", 30)
		application = make_application([dict(MEENA_PLEDGE[0], haircut=30)])

		self.assertEqual(flt(application.proposed_pledges[0].haircut), 30)
		self.assertEqual(application.maximum_loan_amount, 262401)

	def test_current_price_limit_falls_back_to_the_type_haircut(self):
		loan = make_disbursed_meena_loan()
		frappe.db.set_value("Loan Security", "Gold 916", "haircut", 0)
		frappe.db.set_value("Loan Security Type", "Gold", "haircut", 25)

		self.assertEqual(flt(get_total_pledged_security_value(loan.name), 2), flt(374859 * 0.75, 2))

	def test_loan_keeps_the_slab_its_application_was_priced_on(self):
		application = make_application(MEENA_PLEDGE)

		# A ₹4,00,000 loan sanctioned in between moves the borrower to the 75% slab
		other = make_application([{"loan_security": "Gold 999", "qty": 60, "haircut": 15}], loan_amount=400000)
		make_loan(other.name).submit()

		self.assertEqual(flt(make_loan(application.name).gold_ltv_cap), 80)

	def test_loan_with_a_larger_amount_works_out_its_own_cap(self):
		# ₹3,50,000 of gold supports ₹2,80,000, but the application asks for ₹2,00,000: 85% slab
		application = make_application(
			[{"loan_security": "Gold 999", "qty": 35, "haircut": 15}], loan_amount=200000
		)
		self.assertEqual(application.maximum_loan_amount, 280000)
		self.assertEqual(flt(application.gold_ltv_cap), 85)

		loan = make_loan(application.name)
		self.assertEqual(flt(loan.gold_ltv_cap), 85)

		loan.loan_amount = 280000
		loan.save()
		self.assertEqual(flt(loan.gold_ltv_cap), 80)

	def test_credit_assessment_for_gold_pledged_against_a_loan(self):
		frappe.db.set_single_value("Lending Settings", "gold_credit_assessment_above", 250000)
		loan = create_loan(APPLICANT, CONSUMPTION_PRODUCT, 299887, "Repay Over Number of Periods", 12)

		with self.assertRaises(frappe.ValidationError):
			create_loan_security_assignment(loan=loan.name, securities=[dict(MEENA_PLEDGE[0])])

		loan.db_set("credit_assessment", "/files/assessment.pdf")
		create_loan_security_assignment(loan=loan.name, securities=[dict(MEENA_PLEDGE[0])])

	def test_patch_sets_the_credit_assessment_threshold(self):
		from lending.patches.v16_0.set_gold_credit_assessment_threshold import execute

		frappe.db.delete("Singles", {"doctype": "Lending Settings", "field": "gold_credit_assessment_above"})
		execute()
		self.assertEqual(flt(frappe.db.get_single_value("Lending Settings", "gold_credit_assessment_above")), 250000)

		frappe.db.set_single_value("Lending Settings", "gold_credit_assessment_above", 0)
		execute()
		self.assertFalse(flt(frappe.db.get_single_value("Lending Settings", "gold_credit_assessment_above")))

	def test_invalid_slabs(self):
		invalid_slabs = [
			[{"up_to_amount": 500000, "ltv": 80}, {"up_to_amount": 250000, "ltv": 85}, {"ltv": 75}],
			[{"ltv": 85}, {"ltv": 75}],
			[{"up_to_amount": 250000, "ltv": 85}],
		]
		for slabs in invalid_slabs:
			product = frappe.get_doc("Loan Product", CONSUMPTION_PRODUCT)
			product.set("gold_ltv_slabs", slabs)
			self.assertRaises(frappe.ValidationError, product.save)

		product = frappe.get_doc("Loan Product", INCOME_PRODUCT)
		product.set("gold_ltv_slabs", RBI_SLABS)
		self.assertRaises(frappe.ValidationError, product.save)


def make_application(pledges, loan_product=CONSUMPTION_PRODUCT, loan_amount=None, credit_assessment=None):
	application = create_loan_application(
		"_Test Company",
		APPLICANT,
		loan_product,
		[dict(pledge) for pledge in pledges],
		"Repay Over Number of Periods",
		12,
		do_not_save=True,
	)
	application.loan_amount = loan_amount
	application.credit_assessment = credit_assessment
	application.status = "Approved"
	application.save()
	application.submit()
	return application


def make_loan(loan_application, loan_product=CONSUMPTION_PRODUCT):
	create_loan_security_assignment(loan_application)
	return create_loan_with_security(
		APPLICANT, loan_product, "Repay Over Number of Periods", 12, loan_application
	)


def make_disbursed_meena_loan():
	loan = make_loan(make_application(MEENA_PLEDGE).name)
	loan.submit()
	make_loan_disbursement_entry(loan.name, loan.loan_amount)
	return loan


def setup_gold_securities():
	if not frappe.db.exists("Loan Security Type", "Gold"):
		frappe.get_doc(
			{
				"doctype": "Loan Security Type",
				"loan_security_type": "Gold",
				"metal": "Gold",
				"haircut": 15,
				"loan_to_value_ratio": 85,
			}
		).insert(ignore_permissions=True)

	for security, price in (("Gold 916", 9000), ("Gold 999", 10000)):
		if not frappe.db.exists("Loan Security", security):
			frappe.get_doc(
				{
					"doctype": "Loan Security",
					"loan_security_type": "Gold",
					"loan_security_code": security,
					"loan_security_name": security,
					"haircut": 15,
					"loan_to_value_ratio": 85,
				}
			).insert(ignore_permissions=True)
		set_gold_price(security, price)


def set_gold_price(security, price):
	create_loan_security_price(security, price, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)


def setup_gold_products():
	for product, purpose, slabs in (
		(CONSUMPTION_PRODUCT, "Consumption", RBI_SLABS),
		("Gold Consumption Loan No Slabs", "Consumption", []),
		(INCOME_PRODUCT, "Income Generating", []),
	):
		loan_product = create_loan_product(
			product,
			product,
			2000000,
			12,
			25,
			1,
			5,
			repayment_schedule_type="Monthly as per repayment start date",
			collection_offset_sequence_for_standard_asset="Test EMI Based Standard Loan Demand Offset Order",
		)
		loan_product.gold_loan_purpose = purpose
		loan_product.set("gold_ltv_slabs", slabs)
		loan_product.save()
