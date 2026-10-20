# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, flt, nowdate

from lending.gold_loan.test_gold_loan_ltv import (
	APPLICANT,
	CONSUMPTION_PRODUCT,
	make_application,
	setup_gold_products,
	setup_gold_securities,
)
from lending.loan_management.doctype.loan.loan import unpledge_security
from lending.tests.test_utils import (
	create_loan,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_with_security,
	make_customer,
	master_init,
)
from lending.tests.utils import LendingTestSuite

OTHER_APPLICANT = "_Test Gold Loan Customer 2"


class TestGoldArticles(LendingTestSuite):
	def setUp(self):
		master_init()
		make_customer(APPLICANT)
		make_customer(OTHER_APPLICANT)
		create_loan_security_type()
		create_loan_security()
		setup_gold_securities()
		setup_gold_products()
		frappe.db.set_single_value("Lending Settings", "gold_credit_assessment_above", 0)

	def test_meenas_articles_are_pledged_in_one_packet(self):
		necklace, bangles = make_meena_articles()
		assignment = make_assignment(make_loan(), [necklace, bangles], lien_reference="PKT-1041")

		self.assertEqual([flt(row.qty, 3) for row in assignment.articles], [22, 19.651])
		self.assertEqual({row.loan_security for row in assignment.articles}, {"Gold 916"})

		(line,) = assignment.securities
		self.assertEqual((line.loan_security, flt(line.qty, 3)), ("Gold 916", 41.651))
		# The slab haircut runs on the line built from the articles
		self.assertAlmostEqual(flt(line.haircut), 20, places=2)
		self.assertEqual(assignment.maximum_loan_value, 299887)

		self.assertEqual(frappe.db.get_value("Loan Security Assignment", assignment.name, "status"), "Pledged")
		for article in (necklace, bangles):
			article.reload()
			self.assertEqual(article.status, "Pledged")
			self.assertEqual(article.current_assignment, assignment.name)
			self.assertEqual(article.packet_number, "PKT-1041")

		self.assertEqual((necklace.gross_weight, necklace.net_weight, necklace.fineness), (25, 22, 916))
		self.assertEqual(bangles.fineness, 900)

	def test_share_lines_are_unaffected(self):
		create_loan_security_price(
			"Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
		)
		necklace = make_article("Necklace", 25, 3, 916)
		securities = [
			{"loan_security": "Test Security 1", "qty": 100, "haircut": 50},
			{"loan_security": "Gold 999", "qty": 5},
		]
		assignment = make_assignment(make_loan(), [necklace], securities=securities)

		shares, gold = assignment.securities
		self.assertEqual((shares.loan_security, flt(shares.qty), flt(shares.haircut)), ("Test Security 1", 100, 50))
		# The typed gold line is replaced by the line of the article's purity
		self.assertEqual((gold.loan_security, flt(gold.qty, 3)), ("Gold 916", 22))

	def test_released_articles_can_be_pledged_again(self):
		necklace, bangles = make_meena_articles()
		loan = make_loan()
		assignment = make_assignment(loan, [necklace, bangles])

		release = unpledge_security(loan=loan.name, security_map={"Gold 916": 41.651}, submit=1, approve=1)
		for article in (necklace, bangles):
			article.reload()
			self.assertEqual((article.status, article.current_assignment), ("Released", None))

		row = frappe.get_doc("Loan Security Assignment", assignment.name).articles[0]
		self.assertEqual((row.status, row.released_or_sold_in), ("Released", release.name))

		release.cancel()
		necklace.reload()
		self.assertEqual((necklace.status, necklace.current_assignment), ("Pledged", assignment.name))

		release = unpledge_security(loan=loan.name, security_map={"Gold 916": 41.651}, submit=1, approve=1)
		second = make_assignment(make_loan(), [necklace, bangles], from_last_assay=True)

		self.assertEqual([(row.gross_weight, row.deduction_weight, row.fineness) for row in second.articles], [(25, 3, 916), (20, 0, 900)])
		self.assertEqual(flt(second.securities[0].qty, 3), 41.651)
		necklace.reload()
		self.assertEqual((necklace.status, necklace.current_assignment), ("Pledged", second.name))

		# Cancelling the release would put the articles on two open assignments
		assert_refused_and_rolled_back(self, release.cancel, f"now pledged on Loan Security Assignment .*{second.name}")

		# The old assignment still saves after its articles moved on
		first = frappe.get_doc("Loan Security Assignment", assignment.name)
		first.certificate_acknowledgement = "/files/acknowledgement.pdf"
		first.save()
		self.assertEqual(flt(first.securities[0].qty, 3), 41.651)
		self.assertEqual(frappe.db.get_value("Gold Article", necklace.name, "current_assignment"), second.name)

	def test_partial_release_keeps_the_articles_pledged(self):
		necklace, bangles = make_meena_articles()
		loan = make_loan()
		make_assignment(loan, [necklace, bangles])

		unpledge_security(loan=loan.name, security_map={"Gold 916": 1}, submit=1, approve=1)
		self.assertEqual(frappe.db.get_value("Gold Article", necklace.name, "status"), "Pledged")

	def test_articles_that_cannot_be_pledged(self):
		# The first direct pledge sets the applicant's sanctioned limit, so book the loans first
		first, second = make_loan(), make_loan()
		necklace = make_article("Necklace", 25, 3, 916)
		make_assignment(first, [necklace])

		other = make_article("Ring", 5, 0, 916, applicant=OTHER_APPLICANT)
		sold = make_article("Chain", 10, 0, 916)
		sold.db_set("status", "Sold")

		for article, reason in ((necklace, "already pledged"), (other, "another applicant"), (sold, "sold")):
			with self.assertRaisesRegex(frappe.ValidationError, reason):
				make_assignment(second, [article])

	def test_cancel_puts_the_articles_back(self):
		necklace = make_article("Necklace", 25, 3, 916)
		# An assay the article came with, for example from an import
		before = {"gross_weight": 30, "deduction_weight": 2, "net_weight": 28, "fineness": 900, "defects": "Dent on clasp"}
		# db_set adds modified and modified_by to the dict it is given
		necklace.db_set(dict(before))
		assignment = make_assignment(make_loan(), [necklace])
		self.assertEqual(frappe.db.get_value("Gold Article", necklace.name, "gross_weight"), 25)

		assignment.cancel()
		necklace.reload()
		self.assertEqual((necklace.status, necklace.current_assignment), ("Available", None))
		self.assertEqual({fieldname: necklace.get(fieldname) for fieldname in before}, before)

	def test_packet_number_with_track_lien(self):
		first, second = make_loan(), make_loan()
		make_assignment(first, [make_article("Necklace", 25, 3, 916)])

		frappe.db.set_value("Loan Security Type", "Gold", "track_lien", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "Lien Reference"):
			make_assignment(second, [make_article("Bangles", 20, 0, 900)])

		assignment = make_assignment(second, [make_article("Coin", 8, 0, 999, kind="Coin")], lien_reference="PKT-7")
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", assignment.name, "status"), "Pledged")

	def test_track_lien_covers_share_lines(self):
		create_loan_security_price(
			"Test Security 1", 500, "Nos", nowdate(), add_days(nowdate(), 1), update_if_existing=True
		)
		share_type = frappe.db.get_value("Loan Security", "Test Security 1", "loan_security_type")
		frappe.db.set_value("Loan Security Type", share_type, "track_lien", 1)
		shares = [{"loan_security": "Test Security 1", "qty": 100, "haircut": 50}]

		with self.assertRaisesRegex(frappe.ValidationError, "Lien Reference"):
			make_assignment(make_loan(), [make_article("Necklace", 25, 3, 916)], securities=shares)

		assignment = make_assignment(
			make_loan(), [make_article("Bangles", 20, 0, 900)], securities=shares, lien_reference="CDSL-881"
		)
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", assignment.name, "status"), "Pledged")

	def test_packet_number_cannot_be_cleared_after_pledge(self):
		frappe.db.set_value("Loan Security Type", "Gold", "track_lien", 1)
		assignment = make_assignment(make_loan(), [make_article("Necklace", 25, 3, 916)], lien_reference="PKT-3")

		assignment.reload()
		assignment.securities[0].lien_reference = None
		with self.assertRaisesRegex(frappe.ValidationError, "Lien Reference"):
			assignment.save()

	def test_an_article_claimed_by_another_pledge_is_refused_at_submit(self):
		from lending.gold_loan.articles import pledge_articles

		# Both loans come before the first pledge, which sets the applicant's sanctioned limit
		first_loan, second_loan = make_loan(), make_loan()
		necklace = make_article("Necklace", 25, 3, 916)
		first = make_assignment(first_loan, [necklace])
		second = make_assignment(second_loan, [make_article("Bangles", 20, 0, 900)])

		# A second request that passed its checks before the first one claimed the necklace
		second.append("articles", {"gold_article": necklace.name, **necklace.flags.assay})
		with self.assertRaisesRegex(frappe.ValidationError, f"already pledged on Loan Security Assignment .*{first.name}"):
			pledge_articles(second)

	def test_release_reference_with_track_lien(self):
		frappe.db.set_value("Loan Security Type", "Gold", "track_lien", 1)
		loan = make_loan()
		make_assignment(loan, [make_article("Necklace", 25, 3, 916)], lien_reference="PKT-1")

		release = unpledge_security(loan=loan.name, security_map={"Gold 916": 22}, submit=1)
		release.status = "Approved"
		assert_refused_and_rolled_back(self, release.save, "Release Reference")

		release.reload()
		release.securities[0].release_reference = "RCPT-1"
		release.status = "Approved"
		release.save()
		self.assertEqual(frappe.db.get_value("Gold Article", {"description": "Necklace"}, "status"), "Released")

	def test_packet_number_on_a_loan_application(self):
		frappe.db.set_value("Loan Security Type", "Gold", "track_lien", 1)
		necklace = make_article("Necklace", 25, 3, 916)
		application = make_application([{"loan_security": "Gold 916", "qty": 22, "haircut": 15}])
		assignment = make_assignment(None, [necklace], loan_application=application.name)

		# The pledge is only requested, so it needs no packet number yet
		self.assertEqual(frappe.db.get_value("Loan Security Assignment", assignment.name, "status"), "Pledge Requested")

		loan = create_loan_with_security(
			APPLICANT, CONSUMPTION_PRODUCT, "Repay Over Number of Periods", 12, application.name
		)
		assert_refused_and_rolled_back(self, loan.submit, "Lien Reference")

		# A correction to the row while the article is on this assignment reaches the article
		frappe.db.set_value("Pledged Article", assignment.articles[0].name, "defects", "Scratch on pendant")
		assignment.reload()
		assignment.securities[0].lien_reference = "PKT-9"
		assignment.save()
		self.assertEqual(frappe.db.get_value("Gold Article", necklace.name, "defects"), "Scratch on pendant")
		loan.reload()
		loan.submit()

		self.assertEqual(frappe.db.get_value("Loan Security Assignment", assignment.name, "status"), "Pledged")
		self.assertEqual(
			frappe.db.get_value("Gold Article", necklace.name, ["status", "packet_number"]), ("Pledged", "PKT-9")
		)

	def test_weight_cap(self):
		frappe.db.set_value("Loan Security Type", "Gold", "max_ornament_weight", 50)
		first, second = make_loan(), make_loan()
		make_assignment(first, make_meena_articles())

		# Meena already has 45 g of ornaments pledged; 10 g more passes the cap, a coin does not count
		with self.assertRaisesRegex(frappe.ValidationError, "above the cap"):
			make_assignment(second, [make_article("Chain", 10, 0, 916)])
		make_assignment(second, [make_article("Coin", 10, 0, 999, kind="Coin")])

	def test_submit_needs_the_declaration_and_the_borrower(self):
		for missing in ("ownership_declaration", "borrower_present_at_assay"):
			assignment = make_assignment(make_loan(), [make_article("Necklace", 25, 3, 916)], submit=False)
			assignment.set(missing, None)
			with self.assertRaisesRegex(frappe.ValidationError, "before you submit"):
				assignment.submit()


def assert_refused_and_rolled_back(test, action, reason):
	# The throw comes after the document's own row is written, so undo that too
	frappe.db.savepoint("gold_article_refusal")
	with test.assertRaisesRegex(frappe.ValidationError, reason):
		action()
	frappe.db.rollback(save_point="gold_article_refusal")


def make_meena_articles():
	return [make_article("Necklace", 25, 3, 916), make_article("Pair of bangles", 20, 0, 900, pieces=2)]


def make_article(description, gross_weight, deduction_weight, fineness, applicant=APPLICANT, kind="Ornament", pieces=1):
	article = frappe.get_doc(
		{
			"doctype": "Gold Article",
			"applicant_type": "Customer",
			"applicant": applicant,
			"article_kind": kind,
			"metal": "Gold",
			"description": description,
			"pieces": pieces,
			"image": "/files/gold-article.jpg",
		}
	).insert()
	# The assay of this pledge, read by make_assignment
	article.flags.assay = {"gross_weight": gross_weight, "deduction_weight": deduction_weight, "fineness": fineness}
	return article


def make_loan():
	return create_loan(APPLICANT, CONSUMPTION_PRODUCT, 299887, "Repay Over Number of Periods", 12)


def make_assignment(
	loan, articles, securities=None, lien_reference=None, loan_application=None, from_last_assay=False, submit=True
):
	assignment = frappe.get_doc(
		{
			"doctype": "Loan Security Assignment",
			"applicant_type": "Customer",
			"applicant": loan.applicant if loan else APPLICANT,
			"company": "_Test Company",
			"loan": loan.name if loan else None,
			"loan_application": loan_application,
			"ownership_declaration": "/files/declaration.pdf",
			"borrower_present_at_assay": 1,
			"securities": securities or [],
			"articles": [
				{"gold_article": article.name, **({} if from_last_assay else article.flags.assay)} for article in articles
			],
		}
	).insert()

	if lien_reference:
		for line in assignment.securities:
			line.lien_reference = lien_reference
		assignment.save()

	if submit:
		assignment.submit()
	return assignment
