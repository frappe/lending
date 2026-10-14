# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, nowdate

from lending.loan_management.doctype.loan.loan import unpledge_security
from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment as create_pledge_from_application,
)
from lending.loan_management.doctype.loan_security_assignment.loan_security_assignment import (
	release_loan_security_assignment,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_qty_map,
)
from lending.tests.test_utils import (
	create_loan,
	create_loan_application,
	create_loan_security,
	create_loan_security_assignment,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_with_security,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)
from lending.tests.utils import LendingTestSuite

APPLICANT = "_Test Loan Customer"


def make_pledge(securities, loan=None, applicant=APPLICANT):
	lsa = frappe.new_doc("Loan Security Assignment")
	lsa.update(
		{
			"applicant_type": "Customer",
			"applicant": applicant,
			"company": "_Test Company",
			"loan": loan,
			"securities": securities,
		}
	)
	return lsa.insert()


def make_loan():
	loan = create_loan(
		"_Test Customer 1",
		"Term Loan Product 5",
		100000,
		"Repay Over Number of Periods",
		12,
		repayment_start_date="2024-04-05",
		posting_date="2024-03-06",
		rate_of_interest=25,
		applicant_type="Customer",
		limit_applicable_start="2024-01-05",
		limit_applicable_end="2024-12-05",
	)
	loan.submit()
	return loan


def make_release(securities):
	release = frappe.new_doc("Loan Security Release")
	release.update(
		{
			"applicant_type": "Customer",
			"applicant": APPLICANT,
			"company": "_Test Company",
			"securities": securities,
		}
	)
	release.insert()
	release.submit()
	return release


class TestLoanSecurityAssignment(LendingTestSuite):
	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price("Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)
		create_loan_security_price("Test Security 2", 250, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True)


	def test_loan_security_validations(self):
		pledge = [
			{
				"loan_security": "Test Security 1",
				"qty": 4000.00,
			}
		]

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			1500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2024-12-05",
		)

		loan.submit()

		lsa = create_loan_security_assignment(loan=loan.name, securities=pledge)

		lsa_doc = frappe.get_doc("Loan Security Assignment", lsa)

		self.assertEqual(lsa_doc.total_security_value, 2000000)
		self.assertEqual(lsa_doc.maximum_loan_value, 1000000)

		self.assertRaises(frappe.exceptions.ValidationError, make_loan_disbursement_entry,
			loan.name, 1200000, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		disbursement = make_loan_disbursement_entry(
			loan.name, 900000, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		self.assertTrue(disbursement)

	def test_direct_pledge_needs_lien_reference(self):
		lsa = make_pledge([{"loan_security": "Test Security 1", "qty": 100}])

		self.assertRaises(frappe.ValidationError, lsa.submit)

		lsa.reload()
		lsa.securities[0].lien_reference = "PSN-55821"
		lsa.submit()

		self.assertEqual(lsa.status, "Pledged")

	def test_application_pledge_needs_lien_reference_before_loan(self):
		loan_application = create_loan_application(
			"_Test Company",
			APPLICANT,
			"Stock Loan",
			[{"loan_security": "Test Security 2", "qty": 8000.00, "haircut": 50}],
			"Repay Over Number of Periods",
			12,
		)
		# Requested, not yet locked: no reference is needed to submit.
		lsa = create_pledge_from_application(loan_application)
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", lsa, "status"), "Pledge Requested")

		loan = create_loan_with_security(
			APPLICANT, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertRaises(frappe.ValidationError, loan.submit)

		pledge_row = frappe.db.get_value("Pledge", {"parent": lsa}, "name")
		frappe.db.set_value("Pledge", pledge_row, "lien_reference", "PSN-55821")
		loan.submit()

		self.assertEqual(frappe.db.get_value("Loan Security Assignment", lsa, "status"), "Pledged")

	def test_disabled_security_cannot_be_pledged(self):
		frappe.db.set_value("Loan Security", "Test Security 1", "disabled", 1)

		self.assertRaises(
			frappe.ValidationError, make_pledge, [{"loan_security": "Test Security 1", "qty": 100}]
		)

	def test_security_disabled_after_the_request_is_not_pledged_by_the_loan(self):
		loan_application = create_loan_application(
			"_Test Company",
			APPLICANT,
			"Stock Loan",
			[{"loan_security": "Test Security 2", "qty": 100, "haircut": 50}],
			"Repay Over Number of Periods",
			12,
		)
		lsa = create_pledge_from_application(loan_application)
		frappe.db.set_value("Pledge", {"parent": lsa}, "lien_reference", "PSN-1")
		frappe.db.set_value("Loan Security", "Test Security 2", "disabled", 1)

		loan = create_loan_with_security(
			APPLICANT, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)

		self.assertRaisesRegex(frappe.ValidationError, "is disabled", loan.submit)

	def test_single_security_share_cap(self):
		frappe.db.set_value("Loan Security Type", "Stock", "max_single_security_pct", 60)

		# 2,00,000 of Test Security 1 against 25,000 of Test Security 2 is 88.89% in one security.
		self.assertRaises(
			frappe.ValidationError,
			make_pledge,
			[
				{"loan_security": "Test Security 1", "qty": 400},
				{"loan_security": "Test Security 2", "qty": 100},
			],
		)

		lsa = make_pledge(
			[
				{"loan_security": "Test Security 1", "qty": 100},
				{"loan_security": "Test Security 2", "qty": 200},
			]
		)
		self.assertEqual(lsa.total_security_value, 100000)

	def test_exposure_cap_counts_existing_pledges(self):
		already_pledged = get_pledged_qty_map(securities=["Test Security 1"]).get("Test Security 1", 0)
		# Room for 1,500 more units at 500 each.
		frappe.db.set_value(
			"Loan Security Type", "Stock", "max_exposure_per_security", (already_pledged + 1500) * 500
		)

		lsa = make_pledge([{"loan_security": "Test Security 1", "qty": 1000, "lien_reference": "PSN-1"}])
		lsa.submit()

		self.assertRaises(
			frappe.ValidationError, make_pledge, [{"loan_security": "Test Security 1", "qty": 600}]
		)
		self.assertTrue(make_pledge([{"loan_security": "Test Security 1", "qty": 500}]))

	def test_release_approval_needs_release_reference(self):
		lsa = make_pledge([{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-1"}])
		lsa.submit()

		release = make_release([{"loan_security": "Test Security 1", "qty": 100}])
		release.status = "Approved"
		self.assertRaises(frappe.ValidationError, release.save)

		release.reload()
		release.securities[0].release_reference = "UNPLEDGE-1"
		release.status = "Approved"
		release.save()

		self.assertTrue(release.unpledge_time)

	def test_top_up_share_is_measured_across_the_loan(self):
		loan = make_loan()
		make_pledge(
			[{"loan_security": "Test Security 1", "qty": 1000, "lien_reference": "PSN-1"}], loan=loan.name
		).submit()
		frappe.db.set_value("Loan Security Type", "Stock", "max_single_security_pct", 60)

		# 1,00,000 next to the 5,00,000 already on the loan is 16.67%, not 100%.
		self.assertTrue(make_pledge([{"loan_security": "Test Security 2", "qty": 400}], loan=loan.name))

		# 10,00,000 next to 5,00,000 is 66.67%.
		self.assertRaises(
			frappe.ValidationError,
			make_pledge,
			[{"loan_security": "Test Security 2", "qty": 4000}],
			loan=loan.name,
		)

	def test_lien_reference_cannot_be_cleared_once_pledged(self):
		lsa = make_pledge([{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-1"}])
		lsa.submit()

		lsa.securities[0].lien_reference = ""
		self.assertRaises(frappe.ValidationError, lsa.save)

	def test_release_button_needs_release_reference(self):
		lsa = make_pledge([{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-1"}])
		lsa.submit()

		self.assertRaises(frappe.ValidationError, release_loan_security_assignment, lsa.name)

		release_loan_security_assignment(lsa.name, " UNPLEDGE-1 ")
		lsa.reload()

		self.assertEqual(lsa.status, "Released")
		self.assertEqual(lsa.release_reference, "UNPLEDGE-1")

	def test_unpledge_security_takes_release_references(self):
		loan = make_loan()
		make_pledge(
			[{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-1"}], loan=loan.name
		).submit()

		self.assertRaises(
			frappe.ValidationError, unpledge_security, loan=loan.name, save=1, submit=1, approve=1
		)

		release = unpledge_security(
			loan=loan.name,
			save=1,
			submit=1,
			approve=1,
			release_references={"Test Security 1": "UNPLEDGE-1"},
		)
		self.assertEqual(release.status, "Approved")
		self.assertEqual(release.securities[0].release_reference, "UNPLEDGE-1")

	def test_requested_pledge_holds_no_exposure_until_the_loan(self):
		loan_application = create_loan_application(
			"_Test Company",
			APPLICANT,
			"Stock Loan",
			[{"loan_security": "Test Security 2", "qty": 8000.00, "haircut": 50}],
			"Repay Over Number of Periods",
			12,
		)
		lsa = create_pledge_from_application(loan_application)
		pledge_row = frappe.db.get_value("Pledge", {"parent": lsa}, "name")
		frappe.db.set_value("Pledge", pledge_row, "lien_reference", "PSN-1")

		already_pledged = get_pledged_qty_map(securities=["Test Security 2"]).get("Test Security 2", 0)
		# Room for 100 more units at 250 each, not for the 8,000 requested as well.
		frappe.db.set_value(
			"Loan Security Type", "Stock", "max_exposure_per_security", (already_pledged + 100) * 250
		)

		# The requested pledge is not counted, so another borrower's pledge that fits on its own goes through.
		make_pledge(
			[{"loan_security": "Test Security 2", "qty": 100, "lien_reference": "PSN-2"}],
			applicant="_Test Loan Customer 1",
		).submit()

		# Creating the loan would mark the 8,000 Pledged, so the cap is checked again.
		loan = create_loan_with_security(
			APPLICANT, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertRaises(frappe.ValidationError, loan.submit)

	def test_pledge_with_loan_and_application_needs_lien_reference(self):
		loan = make_loan()
		loan_application = create_loan_application(
			"_Test Company",
			APPLICANT,
			"Stock Loan",
			[{"loan_security": "Test Security 2", "qty": 100.00, "haircut": 50}],
			"Repay Over Number of Periods",
			12,
		)

		# Submitting with a loan credits the loan at once, so the lock must already be recorded.
		self.assertRaises(
			frappe.ValidationError, create_pledge_from_application, loan_application, loan=loan.name
		)

	def test_exposure_cap_uses_current_price(self):
		already_pledged = get_pledged_qty_map(securities=["Test Security 1"]).get("Test Security 1", 0)
		# Room for 100 more units at today's price of 500.
		frappe.db.set_value(
			"Loan Security Type", "Stock", "max_exposure_per_security", (already_pledged + 100) * 500
		)

		# 150 units at an old price of 100 would look like room to spare.
		self.assertRaises(
			frappe.ValidationError,
			make_pledge,
			[{"loan_security": "Test Security 1", "qty": 150, "loan_security_price": 100}],
		)

	def test_share_cap_uses_current_price(self):
		loan = make_loan()
		make_pledge(
			[{"loan_security": "Test Security 1", "qty": 1000, "lien_reference": "PSN-1"}], loan=loan.name
		).submit()
		frappe.db.set_value("Loan Security Type", "Stock", "max_single_security_pct", 60)

		# At the old price of 100 this is 4,00,000 next to 5,00,000 on the loan, 44.44%.
		# At today's price of 250 it is 10,00,000, 66.67%.
		self.assertRaises(
			frappe.ValidationError,
			make_pledge,
			[{"loan_security": "Test Security 2", "qty": 4000, "loan_security_price": 100}],
			loan=loan.name,
		)

	def test_left_over_releases_do_not_hide_other_pledges(self):
		before = get_pledged_qty_map(securities=["Test Security 1"]).get("Test Security 1", 0)

		make_pledge(
			[{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-1"}],
			applicant="_Test Loan Customer 1",
		).submit()

		# This applicant releases 100 units, then the assignment is cancelled as well.
		lsa = make_pledge([{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-2"}])
		lsa.submit()
		release = make_release(
			[{"loan_security": "Test Security 1", "qty": 100, "release_reference": "UNPLEDGE-1"}]
		)
		release.status = "Approved"
		release.save()
		lsa.reload()
		lsa.cancel()

		self.assertEqual(
			get_pledged_qty_map(securities=["Test Security 1"]).get("Test Security 1", 0), before + 100
		)
