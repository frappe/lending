# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from lending.collateral.mutual_fund import registry
from lending.collateral.mutual_fund.nav_job import update_navs
from lending.collateral.mutual_fund.sample import (
	OTP,
	SampleNavAdapter,
	SampleRegistryAdapter,
	last_weekday,
)
from lending.collateral.mutual_fund.test_mutual_fund import (
	ELSS,
	FLEXI_CAP,
	MF_TYPE,
	fund_line,
	make_pledge,
	setup_test_data,
)
from lending.loan_integrations.adapters import register
from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_security_sale.test_loan_security_sale import make_sale
from lending.tests.test_utils import (
	create_loan_application,
	create_loan_with_security,
	make_loan_disbursement_entry,
)
from lending.tests.utils import LendingTestSuite

register(SampleRegistryAdapter)
register(SampleNavAdapter)

APPLICANT = "_Test Loan Customer"
PAN = "ABCPR1234K"


def use_registry(key=SampleRegistryAdapter.key):
	frappe.db.set_single_value("Lending Settings", registry.REGISTRY_FIELD, key)


def use_nav(key=SampleNavAdapter.key):
	frappe.db.set_single_value("Lending Settings", registry.NAV_FIELD, key)


def make_requested_pledge(qty=4000):
	loan_application = create_loan_application(
		"_Test Company",
		APPLICANT,
		"Stock Loan",
		[{"loan_security": FLEXI_CAP, "qty": qty, "haircut": 50}],
		"Repay Over Number of Periods",
		12,
	)
	create_loan_security_assignment(loan_application)
	lsa = frappe.get_doc("Loan Security Assignment", {"loan_application": loan_application})
	lsa.securities[0].update(fund_line(FLEXI_CAP, qty=qty))
	lsa.save()
	return loan_application, lsa


def mark_lien(lsa):
	registry.request_lien(lsa.name)
	registry.confirm_lien(lsa.name, OTP)
	lsa.reload()


def make_pledged_loan(qty=4000):
	loan_application, lsa = make_requested_pledge(qty)
	mark_lien(lsa)
	loan = create_loan_with_security(APPLICANT, "Stock Loan", "Repay Over Number of Periods", 12, loan_application)
	loan.submit()
	return loan


class TestLien(LendingTestSuite):
	def setUp(self):
		setup_test_data()
		use_registry()

	def test_a_loan_waits_for_the_lien(self):
		loan_application, lsa = make_requested_pledge()
		loan = create_loan_with_security(APPLICANT, "Stock Loan", "Repay Over Number of Periods", 12, loan_application)
		with self.assertRaisesRegex(frappe.ValidationError, "Mark the lien"):
			loan.submit()

		mark_lien(lsa)
		loan.reload()
		loan.submit()
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", lsa.name, "status"), "Pledged")

	def test_a_confirmed_lien_fills_each_reference(self):
		_, lsa = make_requested_pledge()
		registry.request_lien(lsa.name)
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", lsa.name, "lien_status"), "OTP Sent")

		registry.confirm_lien(lsa.name, OTP)
		lsa.reload()
		self.assertEqual(lsa.lien_status, "Marked")
		self.assertTrue(lsa.securities[0].lien_reference.startswith("LIEN-"))

	def test_a_wrong_otp_leaves_the_lien_unmarked_and_logged(self):
		_, lsa = make_requested_pledge()
		registry.request_lien(lsa.name)

		self.assertIsNone(registry.confirm_lien(lsa.name, "000000"))
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", lsa.name, "lien_status"), "OTP Sent")
		self.assertEqual(
			frappe.db.get_value(
				"Integration Request",
				{"reference_docname": lsa.name, "request_description": "confirm_lien"},
				"status",
			),
			"Failed",
		)

	def test_a_marked_lien_is_not_requested_again(self):
		_, lsa = make_requested_pledge()
		mark_lien(lsa)
		with self.assertRaisesRegex(frappe.ValidationError, "already marked"):
			registry.request_lien(lsa.name)

	def test_a_direct_pledge_waits_for_the_lien(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Mark the lien"):
			make_pledge([fund_line(FLEXI_CAP)])

	def test_demat_units_need_no_registry_lien(self):
		lsa = make_pledge([fund_line(FLEXI_CAP, holding_mode="Demat")])
		self.assertEqual(lsa.status, "Pledged")

	def test_without_a_registry_the_lien_is_entered_by_hand(self):
		use_registry("")
		lsa = make_pledge([fund_line(FLEXI_CAP)])
		self.assertEqual(lsa.status, "Pledged")


class TestHoldings(LendingTestSuite):
	def setUp(self):
		setup_test_data()
		use_registry()
		# Fewer units than any sample folio holds, since a fetch records the folio's units
		_, self.lsa = make_requested_pledge(qty=7)

	def fetch(self, otp=OTP):
		request_id = registry.send_holdings_otp(self.lsa.name, PAN, "9999999999")["request_id"]
		return registry.fetch_holdings(self.lsa.name, PAN, request_id, otp)

	def test_holdings_are_tied_to_their_securities(self):
		holdings = {holding["scheme_name"]: holding for holding in self.fetch()}

		self.assertEqual(holdings[FLEXI_CAP]["loan_security"], FLEXI_CAP)
		self.assertEqual(len(holdings[ELSS]["lots"]), 2)
		unlisted = [holding for holding in holdings.values() if not holding["loan_security"]]
		self.assertEqual(len(unlisted), 1)

	def test_a_wrong_otp_reads_no_folios(self):
		self.assertIsNone(self.fetch("000000"))

	def test_holdings_fill_the_details_of_a_requested_pledge(self):
		holding = next(holding for holding in self.fetch() if holding["loan_security"] == FLEXI_CAP)
		line = {**holding, **holding["lots"][0], "holding_type": "Single", "qty": 10}
		registry.add_holdings(self.lsa.name, [line])

		self.lsa.reload()
		self.assertEqual(self.lsa.securities[0].folio_number, holding["folio_number"])
		# The application fixed the units
		self.assertEqual(self.lsa.securities[0].qty, 7)
		holding = frappe.get_doc("Mutual Fund Holding", self.lsa.securities[0].mutual_fund_holding)
		self.assertEqual(holding.units_held, sum(lot.units for lot in holding.lots))

	def test_holdings_add_lines_to_a_draft(self):
		draft = frappe.new_doc("Loan Security Assignment")
		draft.update({"applicant_type": "Customer", "applicant": APPLICANT, "company": "_Test Company"})
		draft.append("securities", {"loan_security": "Test Security 1", "qty": 10})
		draft.insert()

		holding = next(holding for holding in self.fetch() if holding["loan_security"] == FLEXI_CAP)
		registry.add_holdings(draft.name, [{**holding, **holding["lots"][0], "qty": 25}])

		draft.reload()
		self.assertEqual([row.qty for row in draft.securities if row.loan_security == FLEXI_CAP], [25])


class TestReleaseAndSale(LendingTestSuite):
	def setUp(self):
		setup_test_data()
		use_registry()
		self.loan = make_pledged_loan()
		make_loan_disbursement_entry(self.loan.name, 1000)

	def test_a_release_waits_for_the_lien_to_be_revoked(self):
		release = frappe.new_doc("Loan Security Release")
		release.update(
			{"applicant_type": "Customer", "applicant": APPLICANT, "loan": self.loan.name, "company": "_Test Company"}
		)
		release.append("securities", {"loan_security": FLEXI_CAP, "qty": 100})
		release.insert()
		release.submit()

		release.status = "Approved"
		with self.assertRaisesRegex(frappe.ValidationError, "Revoke the lien"):
			release.save()

		registry.revoke_lien(release.name)
		release.reload()
		self.assertTrue(release.securities[0].release_reference.startswith("REVOKE-"))
		release.status = "Approved"
		release.save()

	def test_a_redemption_fills_the_sale(self):
		sale = make_sale(self.loan.name, reason="Borrower Request")
		sale.append("items", {"loan_security": FLEXI_CAP, "qty": 100})
		sale.save()

		sale.items[0].sold_qty, sale.items[0].sale_price = 100, 90
		sale.save()
		with self.assertRaisesRegex(frappe.ValidationError, "Request the redemption"):
			sale.submit()

		registry.request_redemption(sale.name)
		sale.reload()
		# The sample redeems at 98% of the ₹90 NAV, less 1% exit load and STT
		self.assertEqual(flt(sale.items[0].sale_price), 88.2)
		self.assertEqual(flt(sale.gross_proceeds), 8820)
		self.assertEqual(flt(sale.deductions), flt(88.2 + 0.09, 2))
		self.assertTrue(sale.redemption_reference.startswith("RED-"))
		sale.submit()


class TestNavJob(LendingTestSuite):
	def setUp(self):
		setup_test_data()
		use_nav()
		make_pledge([fund_line(FLEXI_CAP)])
		# A price entered by hand on the NAV date blocks the update (3.4), so the old prices start earlier
		frappe.db.set_value(
			"Loan Security Price",
			{"loan_security": ("in", [FLEXI_CAP, ELSS])},
			"valid_from",
			add_days(nowdate(), -3),
		)

	def test_the_job_prices_each_type_once_a_day(self):
		update_navs()
		filters = {
			"loan_security_type": MF_TYPE,
			"price_date": last_weekday(getdate()),
			"docstatus": 1,
		}
		self.assertEqual(frappe.db.count("Loan Security Price Update", filters), 1)

		update_navs()
		self.assertEqual(frappe.db.count("Loan Security Price Update", filters), 1)

	def test_no_adapter_no_job(self):
		use_nav("")
		update_navs()
		self.assertFalse(frappe.db.exists("Loan Security Price Update", {"loan_security_type": MF_TYPE}))
