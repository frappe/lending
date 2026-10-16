# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, nowdate

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)
from lending.tests.test_utils import (
	create_loan,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_release,
	create_loan_security_type,
	init_customers,
	init_loan_products,
	make_loan_disbursement_entry,
	master_init,
)
from lending.tests.utils import LendingTestSuite


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

	def make_submitted_loan(self):
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
		return loan

	def test_cancel_pledge_after_release_is_refused(self):
		loan = self.make_submitted_loan()

		pledge = [{"loan_security": "Test Security 1", "qty": 100}]
		first = create_loan_security_assignment(loan=loan.name, securities=pledge)
		create_loan_security_assignment(loan=loan.name, securities=pledge)

		release = create_loan_security_release("_Test Customer 1", "Customer", pledge, loan=loan.name)

		first_doc = frappe.get_doc("Loan Security Assignment", first)
		self.assertRaises(frappe.ValidationError, first_doc.cancel)
		self.assertEqual(get_pledged_security_qty(loan=loan.name)["Test Security 1"], 100)

		later = create_loan_security_assignment(loan=loan.name, securities=pledge)
		frappe.get_doc("Loan Security Assignment", later).cancel()
		self.assertEqual(get_pledged_security_qty(loan=loan.name)["Test Security 1"], 100)

		release.cancel()
		first_doc.reload()
		first_doc.cancel()
		self.assertEqual(get_pledged_security_qty(loan=loan.name)["Test Security 1"], 100)

	def test_amended_release_blocks_cancel_of_pledge_made_before_it(self):
		loan = self.make_submitted_loan()

		pledge = [{"loan_security": "Test Security 1", "qty": 100}]
		create_loan_security_assignment(loan=loan.name, securities=pledge)
		release = create_loan_security_release("_Test Customer 1", "Customer", pledge, loan=loan.name)
		release.cancel()

		middle = create_loan_security_assignment(loan=loan.name, securities=pledge)

		amended = frappe.copy_doc(release)
		amended.amended_from = release.name
		amended.docstatus = 0
		amended.status = "Requested"
		amended.insert()
		amended.submit()
		amended.status = "Approved"
		amended.save()

		self.assertGreater(amended.unpledge_time, release.unpledge_time)
		self.assertRaises(frappe.ValidationError, frappe.get_doc("Loan Security Assignment", middle).cancel)

	def test_release_without_time_or_loan_blocks_cancel(self):
		loan = self.make_submitted_loan()

		pledge = [{"loan_security": "Test Security 1", "qty": 100}]
		first = create_loan_security_assignment(loan=loan.name, securities=pledge)

		release = create_loan_security_release("_Test Customer 1", "Customer", pledge)
		self.assertRaises(frappe.ValidationError, frappe.get_doc("Loan Security Assignment", first).cancel)

		release.db_set("unpledge_time", None)
		later = create_loan_security_assignment(loan=loan.name, securities=pledge)
		self.assertRaises(frappe.ValidationError, frappe.get_doc("Loan Security Assignment", later).cancel)
