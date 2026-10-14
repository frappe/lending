# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, now_datetime, nowdate

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
from lending.patches.v16_0.link_releases_to_assignments import (
	execute as link_releases_to_assignments,
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
	make_customer,
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


def make_unlinked_release(applicant, qty):
	# An approved release saved before releases were linked to assignments.
	release = frappe.new_doc("Loan Security Release")
	release.update(
		{
			"applicant_type": "Customer",
			"applicant": applicant,
			"company": "_Test Company",
			"status": "Approved",
			"docstatus": 1,
			"unpledge_time": now_datetime(),
			"securities": [{"loan_security": "Test Security 1", "qty": qty, "release_reference": "OLD-1"}],
		}
	)
	release.flags.ignore_validate = True
	return release.insert()


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


def make_release(securities, applicant=APPLICANT):
	release = frappe.new_doc("Loan Security Release")
	release.update(
		{
			"applicant_type": "Customer",
			"applicant": applicant,
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

		# A failed request rolls back, so the release it submitted does not hold the shares.
		frappe.db.savepoint("unpledge")
		self.assertRaises(
			frappe.ValidationError, unpledge_security, loan=loan.name, save=1, submit=1, approve=1
		)
		frappe.db.rollback(save_point="unpledge")

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

	def test_share_cap_keeps_the_pledged_price_once_it_expires(self):
		loan = make_loan()
		make_pledge(
			[
				{"loan_security": "Test Security 1", "qty": 1000, "lien_reference": "PSN-1"},
				{"loan_security": "Test Security 2", "qty": 2000, "lien_reference": "PSN-2"},
			],
			loan=loan.name,
		).submit()
		frappe.db.set_value("Loan Security Type", "Stock", "max_single_security_pct", 60)

		price = frappe.qb.DocType("Loan Security Price")
		frappe.qb.update(price).set(price.valid_upto, add_days(nowdate(), -1)).where(
			price.loan_security == "Test Security 2"
		).run()

		# 5,05,000 next to the 5,00,000 of Test Security 2 at its pledged price is 50.25%.
		self.assertTrue(
			make_pledge([{"loan_security": "Test Security 1", "qty": 10}], loan=loan.name)
		)

	def test_left_over_releases_do_not_hide_other_pledges(self):
		before = get_pledged_qty_map(securities=["Test Security 1"]).get("Test Security 1", 0)

		make_pledge(
			[{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-1"}],
			applicant="_Test Loan Customer 1",
		).submit()

		# A release from before releases were linked to assignments, then the assignment is cancelled.
		lsa = make_pledge([{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-2"}])
		lsa.submit()
		make_unlinked_release(APPLICANT, 100)
		lsa.cancel()

		self.assertEqual(
			get_pledged_qty_map(securities=["Test Security 1"]).get("Test Security 1", 0), before + 100
		)

	def make_pledges(self, applicant, *quantities):
		make_customer(applicant)
		pledges = []
		for qty in quantities:
			lsa = make_pledge(
				[{"loan_security": "Test Security 1", "qty": qty, "lien_reference": f"PSN-{qty}"}],
				applicant=applicant,
			)
			lsa.submit()
			pledges.append(lsa)
		return pledges

	def approve_release(self, applicant, qty, assignment=None):
		release = make_release(
			[
				{
					"loan_security": "Test Security 1",
					"qty": qty,
					"release_reference": "UNPLEDGE-1",
					"loan_security_assignment": assignment,
				}
			],
			applicant=applicant,
		)
		release.status = "Approved"
		release.save()
		return release

	def pledged(self, applicant):
		return get_pledged_qty_map(applicant=applicant, securities=["Test Security 1"]).get(
			"Test Security 1", 0
		)

	def test_released_pledge_cannot_be_cancelled_while_its_release_stands(self):
		applicant = "_Test Cancel Released Pledge Customer"
		first, second = self.make_pledges(applicant, 100, 100)

		# A release without a pledge takes the oldest one, the first.
		release = self.approve_release(applicant, 100)
		self.assertEqual(release.securities[0].loan_security_assignment, first.name)
		self.assertEqual(self.pledged(applicant), 100)

		# Cancelling the first pledge as well would subtract its 100 twice, out of the second.
		# The link check runs after on_cancel, so the failed request rolls back.
		first.reload()
		frappe.db.savepoint("cancel")
		self.assertRaises(frappe.LinkExistsError, first.cancel)
		frappe.db.rollback(save_point="cancel")
		self.assertEqual(self.pledged(applicant), 100)

		self.approve_release(applicant, 100, assignment=second.name)
		self.assertEqual(self.pledged(applicant), 0)

	def test_release_rows_are_split_across_pledges(self):
		applicant = "_Test Split Release Customer"
		first, second = self.make_pledges(applicant, 50, 30)

		release = self.approve_release(applicant, 60)

		self.assertEqual(
			[(row.loan_security_assignment, row.qty) for row in release.securities],
			[(first.name, 50), (second.name, 10)],
		)
		self.assertEqual(self.pledged(applicant), 20)

	def test_a_pledge_cannot_be_released_twice(self):
		applicant = "_Test Double Release Customer"
		first, _second = self.make_pledges(applicant, 50, 50)
		self.approve_release(applicant, 50, assignment=first.name)

		self.assertRaisesRegex(
			frappe.ValidationError, "not yet released", self.approve_release, applicant, 10, first.name
		)

	def test_release_of_more_than_is_pledged_is_refused(self):
		applicant = "_Test Over Release Customer"
		self.make_pledges(applicant, 50, 30)

		self.assertRaises(frappe.ValidationError, self.approve_release, applicant, 100)

	def test_cancelling_the_loan_cancels_its_releases(self):
		loan = make_loan()
		lsa = make_pledge(
			[{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-1"}],
			loan=loan.name,
			applicant=loan.applicant,
		)
		lsa.submit()
		release = unpledge_security(
			loan=loan.name,
			save=1,
			submit=1,
			approve=1,
			release_references={"Test Security 1": "UNPLEDGE-1"},
		)

		loan.reload()
		loan.cancel()

		self.assertEqual(frappe.db.get_value("Loan Security Release", release.name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", lsa.name, "docstatus"), 2)

	def test_cancelling_an_imported_closed_loan_keeps_it_closed(self):
		loan = make_loan()
		make_pledge(
			[{"loan_security": "Test Security 1", "qty": 100, "lien_reference": "PSN-1"}],
			loan=loan.name,
			applicant=loan.applicant,
		).submit()
		unpledge_security(
			loan=loan.name,
			save=1,
			submit=1,
			approve=1,
			release_references={"Test Security 1": "UNPLEDGE-1"},
		)
		frappe.db.set_value("Loan", loan.name, "is_imported", 1)

		loan.reload()
		loan.cancel()

		self.assertEqual(frappe.db.get_value("Loan", loan.name, "status"), "Closed")

	def make_loan_pledges(self, loan, *quantities):
		pledges = []
		for qty in quantities:
			lsa = make_pledge(
				[{"loan_security": "Test Security 1", "qty": qty, "lien_reference": f"PSN-{qty}"}],
				loan=loan.name,
				applicant=loan.applicant,
			)
			lsa.submit()
			pledges.append(lsa)
		return pledges

	def test_rows_split_across_pledges_cannot_release_more_than_the_loan_holds(self):
		loan = self.make_loan_pledges(make_loan(), 50, 50)[0].loan
		# An old release of this loan the patch could not link still lowers what the loan holds.
		old = make_unlinked_release("_Test Customer 1", 50)
		frappe.db.set_value("Loan Security Release", old.name, "loan", loan)

		self.assertRaisesRegex(
			frappe.ValidationError,
			"unpledge more",
			unpledge_security,
			loan=loan,
			security_map={"Test Security 1": 100},
			save=1,
		)

	def test_release_without_a_loan_leaves_the_loans_pledges(self):
		loan = make_loan()
		self.make_loan_pledges(loan, 50)
		(free,) = self.make_pledges(loan.applicant, 50)

		release = self.approve_release(loan.applicant, 50)

		self.assertEqual(
			[(row.loan_security_assignment, row.qty) for row in release.securities], [(free.name, 50)]
		)
		loan.reload()
		loan.cancel()

	def test_a_blank_row_merges_with_a_row_on_the_same_pledge(self):
		applicant = "_Test Merged Release Customer"
		first, second = self.make_pledges(applicant, 50, 30)

		release = make_release(
			[
				{"loan_security": "Test Security 1", "qty": 10, "loan_security_assignment": first.name},
				{"loan_security": "Test Security 1", "qty": 5},
			],
			applicant=applicant,
		)
		self.assertEqual(
			[(row.loan_security_assignment, row.qty) for row in release.securities], [(first.name, 15)]
		)

		release = make_release(
			[
				{"loan_security": "Test Security 1", "qty": 30, "release_reference": "UNPLEDGE-1"},
				{"loan_security": "Test Security 1", "qty": 5, "release_reference": "UNPLEDGE-2"},
			],
			applicant=applicant,
		)
		self.assertEqual(
			[(row.loan_security_assignment, row.qty, row.release_reference) for row in release.securities],
			[(first.name, 35, "UNPLEDGE-1, UNPLEDGE-2")],
		)

	def test_patch_links_approved_releases_before_open_requests(self):
		applicant = "_Test Approved First Customer"
		(pledge,) = self.make_pledges(applicant, 100)
		request = make_unlinked_release(applicant, 100)
		frappe.db.set_value(
			"Loan Security Release", request.name, {"status": "Requested", "unpledge_time": None}
		)
		approved = make_unlinked_release(applicant, 100)

		link_releases_to_assignments()

		self.assertEqual(
			frappe.db.get_value("Unpledge", {"parent": approved.name}, "loan_security_assignment"),
			pledge.name,
		)
		self.assertFalse(frappe.db.get_value("Unpledge", {"parent": request.name}, "loan_security_assignment"))

	def test_old_release_with_nothing_left_to_free_cannot_be_approved(self):
		applicant = "_Test Old Requests Customer"
		self.make_pledges(applicant, 100)
		requests = []
		for _i in range(2):
			release = make_unlinked_release(applicant, 100)
			frappe.db.set_value(
				"Loan Security Release", release.name, {"status": "Requested", "unpledge_time": None}
			)
			requests.append(release)

		link_releases_to_assignments()

		second = frappe.get_doc("Loan Security Release", requests[1].name)
		self.assertFalse(second.securities[0].loan_security_assignment)
		second.status = "Approved"
		self.assertRaisesRegex(frappe.ValidationError, "No pledge is left", second.save)

	def test_patch_links_old_releases_to_the_oldest_pledges(self):
		applicant = "_Test Old Release Customer"
		first, second = self.make_pledges(applicant, 50, 30)
		release = make_unlinked_release(applicant, 60)

		link_releases_to_assignments()

		release.reload()
		self.assertEqual(
			sorted((row.loan_security_assignment, row.qty) for row in release.securities),
			sorted([(first.name, 50), (second.name, 10)]),
		)
		self.assertEqual(self.pledged(applicant), 20)
		first.reload()
		self.assertRaises(frappe.LinkExistsError, first.cancel)
