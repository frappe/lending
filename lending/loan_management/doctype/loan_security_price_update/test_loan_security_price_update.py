# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import get_datetime

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.tests.test_utils import create_loan_security, create_loan_security_type
from lending.tests.utils import LendingTestSuite

# 2030-01-04 is a Friday
FRIDAY = "2030-01-04"
HOLIDAY_LIST = "_Test Price Update Holidays"


class TestLoanSecurityPriceUpdate(LendingTestSuite):
	def setUp(self):
		create_loan_security_type()
		create_loan_security()
		make_holiday_list()
		frappe.db.set_value("Loan Security Type", "Stock", "price_validity_days", 1)

	def test_one_day_price_runs_to_the_next_working_day(self):
		update = make_price_update(FRIDAY, {"Test Security 1": 600})

		price = get_price(update.name, "Test Security 1")
		self.assertEqual(price.loan_security_price, 600)
		self.assertEqual(price.valid_from, get_datetime("2030-01-04 00:00:00"))
		self.assertEqual(price.valid_upto, get_datetime("2030-01-06 23:59:59"))

	def test_validity_counts_working_days(self):
		frappe.db.set_value("Loan Security Type", "Stock", "price_validity_days", 3)
		update = make_price_update(FRIDAY, {"Test Security 1": 600})

		# Monday, Tuesday and Wednesday are working days, so the price runs out before Wednesday
		self.assertEqual(
			get_price(update.name, "Test Security 1").valid_upto, get_datetime("2030-01-08 23:59:59")
		)

	def test_blank_validity_counts_as_one_day(self):
		frappe.db.set_value("Loan Security Type", "Stock", "price_validity_days", 0)
		update = make_price_update("2030-01-07", {"Test Security 1": 600})

		self.assertEqual(
			get_price(update.name, "Test Security 1").valid_upto, get_datetime("2030-01-07 23:59:59")
		)

	def test_cancel_deletes_its_prices(self):
		update = make_price_update(FRIDAY, {"Test Security 1": 600, "Test Security 2": 300})
		self.assertEqual(frappe.db.count("Loan Security Price", {"price_update": update.name}), 2)

		update.cancel()
		self.assertEqual(frappe.db.count("Loan Security Price", {"price_update": update.name}), 0)

	def test_next_update_ends_the_running_price_and_cancel_restores_it(self):
		frappe.db.set_value("Loan Security Type", "Stock", "price_validity_days", 2)
		monday = make_price_update("2030-01-07", {"Test Security 1": 600})
		monday_price = get_price(monday.name, "Test Security 1")
		self.assertEqual(monday_price.valid_upto, get_datetime("2030-01-08 23:59:59"))

		tuesday = make_price_update("2030-01-08", {"Test Security 1": 610})
		self.assertEqual(
			frappe.db.get_value("Loan Security Price", monday_price.name, "valid_upto"),
			get_datetime("2030-01-07 23:59:59"),
		)

		tuesday.cancel()
		self.assertEqual(
			frappe.db.get_value("Loan Security Price", monday_price.name, "valid_upto"),
			get_datetime("2030-01-08 23:59:59"),
		)

	def test_cancel_does_not_restore_over_a_later_price(self):
		month_price = frappe.get_doc(
			{
				"doctype": "Loan Security Price",
				"loan_security": "Test Security 1",
				"loan_security_price": 500,
				"valid_from": "2030-01-01 00:00:00",
				"valid_upto": "2030-01-31 23:59:59",
			}
		).insert()
		monday = make_price_update("2030-01-07", {"Test Security 1": 600})
		frappe.get_doc(
			{
				"doctype": "Loan Security Price",
				"loan_security": "Test Security 1",
				"loan_security_price": 620,
				"valid_from": "2030-01-08 00:00:00",
				"valid_upto": "2030-01-10 23:59:59",
			}
		).insert()

		monday.cancel()
		self.assertEqual(
			frappe.db.get_value("Loan Security Price", month_price.name, "valid_upto"),
			get_datetime("2030-01-07 23:59:59"),
		)

	def test_rejects_a_price_date_before_an_existing_price(self):
		make_price_update("2030-01-08", {"Test Security 1": 600})
		with self.assertRaises(frappe.ValidationError):
			make_price_update("2030-01-07", {"Test Security 1": 590})

	def test_rejects_bad_rows(self):
		with self.assertRaises(frappe.ValidationError):
			make_price_update(FRIDAY, {"Test Security 1": 0})

		other_type = make_other_type_security()
		with self.assertRaises(frappe.ValidationError):
			make_price_update(FRIDAY, {other_type: 100})

		update = make_price_update(FRIDAY, {"Test Security 1": 600}, submit=False)
		update.append("items", {"loan_security": "Test Security 1", "price": 610})
		with self.assertRaises(frappe.ValidationError):
			update.save()

	def test_get_securities_lists_pledged_securities(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		customer = frappe.get_doc(get_customer_dict("Price Update Customer")).insert().name
		create_loan_security_assignment(
			applicant=customer,
			applicant_type="Customer",
			securities=[{"loan_security": "Test Security 2", "qty": 10}],
			company="_Test Company",
		)

		update = make_price_update(FRIDAY, {"Test Security 1": 600}, submit=False)
		self.assertGreaterEqual(update.missing_count, 1)

		update.get_securities()
		self.assertIn("Test Security 2", [row.loan_security for row in update.items])
		self.assertEqual(update.missing_count, 0)

	def test_get_securities_lists_securities_nobody_pledged(self):
		other_type = make_other_type_security()
		update = make_price_update(FRIDAY, {"Test Security 1": 600}, submit=False)
		update.append("items", {})

		update.get_securities()
		names = {row.loan_security: row.loan_security_name for row in update.items}

		self.assertEqual(names["Test Security 2"], "Test Security 2")
		self.assertNotIn(other_type, names)
		self.assertNotIn(None, names)


def make_price_update(price_date, prices, submit=True):
	update = frappe.new_doc("Loan Security Price Update")
	update.loan_security_type = "Stock"
	update.price_date = price_date
	update.holiday_list = HOLIDAY_LIST
	for security, price in prices.items():
		update.append("items", {"loan_security": security, "price": price})
	update.save()
	if submit:
		update.submit()
	return update


def get_price(price_update, loan_security):
	return frappe.get_doc(
		"Loan Security Price", {"price_update": price_update, "loan_security": loan_security}
	)


def make_holiday_list():
	if frappe.db.exists("Holiday List", HOLIDAY_LIST):
		return
	frappe.get_doc(
		{
			"doctype": "Holiday List",
			"holiday_list_name": HOLIDAY_LIST,
			"from_date": "2030-01-01",
			"to_date": "2030-12-31",
			"holidays": [
				{"holiday_date": "2030-01-05", "description": "Saturday"},
				{"holiday_date": "2030-01-06", "description": "Sunday"},
			],
		}
	).insert()


def make_other_type_security():
	if not frappe.db.exists("Loan Security Type", "_Test Gold"):
		frappe.get_doc(
			{"doctype": "Loan Security Type", "loan_security_type": "_Test Gold", "loan_to_value_ratio": 75}
		).insert()
	if not frappe.db.exists("Loan Security", "_Test Gold Bar"):
		frappe.get_doc(
			{
				"doctype": "Loan Security",
				"loan_security_type": "_Test Gold",
				"loan_security_code": "_Test Gold Bar",
				"loan_security_name": "_Test Gold Bar",
			}
		).insert()
	return "_Test Gold Bar"
