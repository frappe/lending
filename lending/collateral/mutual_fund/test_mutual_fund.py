# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, getdate, nowdate

from lending.collateral.mutual_fund.nav_file import parse_nav_file, read_nav_file
from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.tests.test_utils import (
	create_loan_application,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_with_security,
	init_customers,
	init_loan_products,
	master_init,
)
from lending.tests.utils import LendingTestSuite

MF_TYPE = "_Test Equity MF"
FLEXI_CAP = "_Test Parag Parikh Flexi Cap Direct Growth"
ELSS = "_Test Aditya Birla ELSS Direct Growth"
CLOSED = "_Test Closed Scheme"
NAV_DATE = "2026-10-16"

# Lines from AMFI's NAVAll.txt of 18 October 2026, with its CRLF line ends
NAV_FILE = "\r\n".join(
	[
		"Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date",
		" ",
		"Open Ended Schemes(Equity Scheme - Flexi Cap Fund)",
		" ",
		"PPFAS Mutual Fund",
		" ",
		"122639;INF879O01027;-;Parag Parikh Flexi Cap Fund;Direct Plan;Growth;90.8844;16-Oct-2026",
		"153964;-;INF879O01308;Parag Parikh Flexi Cap Fund;Direct Plan;Monthly IDCW Payout;90.8844;16-Oct-2026",
		"119544;INF209K01UN8;-;Aditya Birla Sun Life ELSS Tax Saver Fund;Direct Plan;GROWTH;66.15;16-Oct-2026",
		"133264;INF204KA1YU4;-;Nippon India Gilt Fund;Regular Plan;Bonus Option;13.0522;02-Jul-2018",
		"151835;-;INF0QA701029;Bajaj Finserv Liquid Fund;Direct Plan;Daily - IDCW;1034.6939;18-Oct-2026",
		"100001;-;-;Wound Up Fund;Direct Plan;Growth;N.A.;16-Oct-2026",
	]
)


class TestMutualFundPledge(LendingTestSuite):
	def setUp(self):
		setup_test_data()

	def test_single_holder_pledge_is_accepted(self):
		lsa = make_pledge([fund_line(FLEXI_CAP)])
		self.assertEqual(lsa.status, "Pledged")

	def test_minor_folio_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "minor"):
			make_pledge([fund_line(FLEXI_CAP, holding_type="Minor")])

	def test_joint_folio_needs_every_holder_to_sign(self):
		with self.assertRaisesRegex(frappe.ValidationError, "must sign the lien"):
			make_pledge([fund_line(FLEXI_CAP, holding_type="Joint")])

		lsa = make_pledge([fund_line(FLEXI_CAP, holding_type="Joint", all_holders_signed=1)])
		self.assertEqual(lsa.status, "Pledged")

	def test_units_in_lock_in_are_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "locked in"):
			make_pledge([fund_line(ELSS, purchase_date=add_days(nowdate(), -1094))])

		lsa = make_pledge([fund_line(ELSS, purchase_date=add_days(nowdate(), -1095))])
		self.assertEqual(lsa.status, "Pledged")

	def test_lock_in_needs_the_purchase_date(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Purchase Date"):
			make_pledge([fund_line(ELSS)])

	def test_direct_pledge_needs_the_folio(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Folio Number"):
			make_pledge([fund_line(FLEXI_CAP, folio_number=None)])

	def test_pledged_details_cannot_be_cleared(self):
		lsa = make_pledge([fund_line(ELSS, purchase_date=add_days(nowdate(), -1095))])
		self.assertEqual(lsa.status, "Pledged")

		for fieldname in ("folio_number", "holding_type", "purchase_date"):
			lsa.reload()
			lsa.securities[0].set(fieldname, None)
			with self.assertRaisesRegex(frappe.ValidationError, "Enter the"):
				lsa.save()

	def test_purchases_of_one_scheme_go_on_separate_lines(self):
		from lending.loan_management.doctype.loan.loan import unpledge_security

		lsa = make_pledge(
			[
				fund_line(ELSS, qty=300, purchase_date="2021-01-15"),
				fund_line(ELSS, qty=200, purchase_date="2022-06-15"),
			]
		)
		self.assertEqual(lsa.status, "Pledged")

		# Releasing the pledge frees both purchases, not only the first line
		release = unpledge_security(loan_security_assignment=lsa.name)
		self.assertEqual([(row.loan_security, row.qty) for row in release.securities], [(ELSS, 500)])

	def test_the_same_purchase_twice_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "added multiple times"):
			make_pledge(
				[
					fund_line(ELSS, qty=300, purchase_date="2021-01-15"),
					fund_line(ELSS, qty=200, purchase_date="2021-01-15"),
				]
			)

	def test_a_share_twice_is_still_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "added multiple times"):
			make_pledge(
				[
					{"loan_security": "Test Security 1", "qty": 100},
					{"loan_security": "Test Security 1", "qty": 50},
				]
			)

	def test_shares_line_needs_no_folio(self):
		lsa = make_pledge(
			[{"loan_security": "Test Security 1", "qty": 100}, fund_line(FLEXI_CAP, qty=100)]
		)
		self.assertEqual(lsa.status, "Pledged")

	def test_application_pledge_is_checked_when_the_loan_is_submitted(self):
		applicant = "_Test Loan Customer"
		loan_application = create_loan_application(
			"_Test Company",
			applicant,
			"Stock Loan",
			[{"loan_security": FLEXI_CAP, "qty": 4000, "haircut": 50}],
			"Repay Over Number of Periods",
			12,
		)
		# The application submits the pledge at once, with no folio, as Pledge Requested
		create_loan_security_assignment(loan_application)
		name = frappe.db.get_value("Loan Security Assignment", {"loan_application": loan_application})
		loan = create_loan_with_security(
			applicant, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Folio Number"):
			loan.submit()

		lsa = frappe.get_doc("Loan Security Assignment", name)
		lsa.securities[0].update(fund_line(FLEXI_CAP, qty=4000))
		lsa.save()
		loan.reload()
		loan.submit()
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", name, "status"), "Pledged")

	def test_minor_folio_cannot_be_entered_after_submit(self):
		loan_application = create_loan_application(
			"_Test Company",
			"_Test Loan Customer",
			"Stock Loan",
			[{"loan_security": FLEXI_CAP, "qty": 4000, "haircut": 50}],
			"Repay Over Number of Periods",
			12,
		)
		create_loan_security_assignment(loan_application)
		lsa = frappe.get_doc("Loan Security Assignment", {"loan_application": loan_application})
		lsa.securities[0].update(fund_line(FLEXI_CAP, qty=4000, holding_type="Minor"))
		with self.assertRaisesRegex(frappe.ValidationError, "minor"):
			lsa.save()


class TestNavFile(LendingTestSuite):
	def setUp(self):
		setup_test_data()

	def test_parse_keeps_only_navs_of_the_price_date(self):
		navs = parse_nav_file(NAV_FILE, getdate(NAV_DATE))
		self.assertEqual(navs, {"122639": 90.8844, "153964": 90.8844, "119544": 66.15})

	def test_parse_reads_bytes(self):
		navs = parse_nav_file(NAV_FILE.encode(), getdate(NAV_DATE))
		self.assertEqual(navs["122639"], 90.8844)

	def test_read_fills_pledged_and_listed_securities(self):
		make_pledge([fund_line(ELSS, purchase_date=add_days(nowdate(), -1095))])
		update = make_draft_update(MF_TYPE)
		# Added by hand and not saved: the file has no NAV for it, so it is dropped
		update.append("items", {"loan_security": CLOSED})

		result = read_nav_file(update.as_dict(), make_nav_file(update.name))
		update.reload()

		self.assertEqual(result["filled"], 2)
		self.assertEqual(
			{row.loan_security: row.price for row in update.items}, {FLEXI_CAP: 90.8844, ELSS: 66.15}
		)

	def test_read_skips_securities_nobody_pledged(self):
		update = make_draft_update(MF_TYPE)

		read_nav_file(update.as_dict(), make_nav_file(update.name))
		update.reload()

		self.assertEqual([row.loan_security for row in update.items], [FLEXI_CAP])

	def test_read_skips_disabled_securities(self):
		make_pledge([fund_line(ELSS, purchase_date=add_days(nowdate(), -1095))])
		frappe.db.set_value("Loan Security", ELSS, "disabled", 1)
		update = make_draft_update(MF_TYPE)

		read_nav_file(update.as_dict(), make_nav_file(update.name))
		update.reload()

		self.assertEqual([row.loan_security for row in update.items], [FLEXI_CAP])

	def test_read_saves_and_attaches_to_a_new_update(self):
		update = frappe.new_doc("Loan Security Price Update")
		update.loan_security_type = MF_TYPE
		update.price_date = NAV_DATE
		update.append("items", {"loan_security": FLEXI_CAP})
		file_name = make_nav_file()

		result = read_nav_file(update.as_dict(), file_name)

		self.assertEqual(len(frappe.get_doc("Loan Security Price Update", result["name"]).items), 1)
		self.assertEqual(frappe.db.get_value("File", file_name, "attached_to_name"), result["name"])

	def test_read_refuses_a_file_with_no_nav_on_the_price_date(self):
		update = make_draft_update(MF_TYPE)
		update.price_date = "2026-10-17"
		update.save()
		with self.assertRaisesRegex(frappe.ValidationError, "no NAV dated"):
			read_nav_file(update.as_dict(), make_nav_file(update.name))

	def test_read_needs_the_price_date(self):
		update = frappe.new_doc("Loan Security Price Update")
		update.loan_security_type = MF_TYPE
		# New updates default to today, so the user has cleared the field
		update.price_date = None
		with self.assertRaisesRegex(frappe.ValidationError, "Set the Price Date"):
			read_nav_file(update.as_dict(), make_nav_file())

	def test_read_is_refused_for_a_type_that_is_not_a_mutual_fund(self):
		update = make_draft_update("Stock")
		with self.assertRaisesRegex(frappe.ValidationError, "not a mutual fund"):
			read_nav_file(update.as_dict(), make_nav_file(update.name))


class TestMutualFundType(LendingTestSuite):
	def setUp(self):
		make_mutual_fund_securities()

	def test_marking_a_type_updates_its_securities(self):
		security_type = frappe.get_doc("Loan Security Type", MF_TYPE)
		security_type.is_mutual_fund = 0
		security_type.save()
		self.assertEqual(frappe.db.get_value("Loan Security", FLEXI_CAP, "is_mutual_fund"), 0)

		security_type.is_mutual_fund = 1
		security_type.save()
		self.assertEqual(frappe.db.get_value("Loan Security", FLEXI_CAP, "is_mutual_fund"), 1)


def setup_test_data():
	master_init()
	init_loan_products()
	init_customers()
	create_loan_security_type()
	create_loan_security()
	make_mutual_fund_securities()
	for security, price in (("Test Security 1", 500), (FLEXI_CAP, 90), (ELSS, 66)):
		create_loan_security_price(
			security, price, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
		)


def make_mutual_fund_securities():
	if not frappe.db.exists("Loan Security Type", MF_TYPE):
		frappe.get_doc(
			{
				"doctype": "Loan Security Type",
				"loan_security_type": MF_TYPE,
				"haircut": 50,
				"loan_to_value_ratio": 50,
				"is_mutual_fund": 1,
			}
		).insert(ignore_permissions=True)

	for code, amfi_scheme_code, lock_in_days in (
		(FLEXI_CAP, "122639", 0),
		(ELSS, "119544", 1095),
		(CLOSED, "999999", 0),
	):
		# The site may already hold these real schemes; the test rolls this back
		frappe.db.set_value(
			"Loan Security",
			{"amfi_scheme_code": amfi_scheme_code, "name": ("!=", code)},
			"amfi_scheme_code",
			None,
		)
		if not frappe.db.exists("Loan Security", code):
			frappe.get_doc(
				{
					"doctype": "Loan Security",
					"loan_security_type": MF_TYPE,
					"loan_security_code": code,
					"loan_security_name": code,
					"amfi_scheme_code": amfi_scheme_code,
					"rta": "CAMS",
					"lock_in_days": lock_in_days,
				}
			).insert(ignore_permissions=True)


def fund_line(security, qty=1000, **details):
	line = {
		"loan_security": security,
		"qty": qty,
		"folio_number": "12345678/90",
		"holding_mode": "Statement of Account",
		"holding_type": "Single",
	}
	line.update(details)
	return line


def make_pledge(securities):
	lsa = frappe.new_doc("Loan Security Assignment")
	lsa.applicant_type = "Customer"
	lsa.applicant = "_Test Loan Customer"
	lsa.company = "_Test Company"
	for security in securities:
		lsa.append("securities", security)
	lsa.save()
	lsa.submit()
	return lsa


def make_draft_update(loan_security_type):
	update = frappe.new_doc("Loan Security Price Update")
	update.loan_security_type = loan_security_type
	update.price_date = NAV_DATE
	update.append("items", {"loan_security": FLEXI_CAP if loan_security_type == MF_TYPE else "Test Security 1", "price": 1})
	update.save()
	return update


def make_nav_file(price_update=None):
	file = frappe.get_doc(
		{"doctype": "File", "file_name": "NAVAll.txt", "content": NAV_FILE, "is_private": 1}
	)
	if price_update:
		file.attached_to_doctype = "Loan Security Price Update"
		file.attached_to_name = price_update
	return file.insert(ignore_permissions=True).name
