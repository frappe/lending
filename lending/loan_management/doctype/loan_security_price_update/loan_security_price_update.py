# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_to_date, cint, flt, get_datetime

import erpnext

from lending.loan_management.doctype.loan_security_assignment.loan_security_assignment import (
	lock_loan_securities,
)
from lending.loan_management.utils import add_working_days

SHORTFALL_JOB = "lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall.run_shortfall_check_job"


class LoanSecurityPriceUpdate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_security_price_update_item.loan_security_price_update_item import (
			LoanSecurityPriceUpdateItem,
		)

		amended_from: DF.Link | None
		holiday_list: DF.Link | None
		items: DF.Table[LoanSecurityPriceUpdateItem]
		loan_security_type: DF.Link
		missing_count: DF.Int
		price_date: DF.Date
	# end: auto-generated types

	def before_insert(self):
		if not self.holiday_list:
			self.holiday_list = frappe.get_cached_value(
				"Company", erpnext.get_default_company(), "default_holiday_list"
			)

	def validate(self):
		self.validate_items()
		self.set_missing_count()

	def before_submit(self):
		self.set_previous_prices()

	def on_submit(self):
		self.create_prices()
		# Also recomputes every Sanctioned Loan Amount, which the new prices skipped
		run_shortfall_check()

	def before_cancel(self):
		# An earlier cancel may have handed this update another price to restore. Cancelling saves the
		# rows before on_cancel runs, so a copy loaded before that cancel would write the old price back
		stored = {
			row.name: row
			for row in frappe.get_all(
				"Loan Security Price Update Item",
				filters={"parent": self.name, "parenttype": self.doctype},
				fields=["name", "previous_price", "previous_valid_upto"],
			)
		}
		for row in self.items:
			if stored_row := stored.get(row.name):
				row.previous_price = stored_row.previous_price
				row.previous_valid_upto = stored_row.previous_valid_upto

	def on_cancel(self):
		for price in frappe.get_all("Loan Security Price", {"price_update": self.name}, pluck="name"):
			frappe.delete_doc(
				"Loan Security Price",
				price,
				ignore_permissions=True,
				flags=frappe._dict(skip_sanctioned_limit_update=True),
			)
		self.restore_previous_prices()
		run_shortfall_check()

	@frappe.whitelist()
	def get_securities(self):
		listed = {row.loan_security for row in self.items}
		for security in sorted(self.get_pledged_securities() - listed):
			self.append("items", {"loan_security": security})
		self.set_missing_count()

	def validate_items(self):
		security_types = dict(
			frappe.get_all(
				"Loan Security",
				filters={"name": ("in", [row.loan_security for row in self.items])},
				fields=["name", "loan_security_type"],
				as_list=1,
			)
		)
		listed = set()
		for row in self.items:
			if row.loan_security in listed:
				frappe.throw(
					_("Row {0}: Loan Security {1} is added more than once").format(
						row.idx, frappe.bold(row.loan_security)
					)
				)
			if security_types.get(row.loan_security) != self.loan_security_type:
				frappe.throw(
					_("Row {0}: Loan Security {1} is not of type {2}").format(
						row.idx, frappe.bold(row.loan_security), frappe.bold(self.loan_security_type)
					)
				)
			if flt(row.price) <= 0:
				frappe.throw(
					_("Row {0}: Enter a price for Loan Security {1}").format(
						row.idx, frappe.bold(row.loan_security)
					)
				)
			listed.add(row.loan_security)

	def set_missing_count(self):
		listed = {row.loan_security for row in self.items}
		self.missing_count = len(self.get_pledged_securities() - listed)

	def create_prices(self):
		valid_from = get_datetime(self.price_date)
		valid_upto = get_datetime(f"{self.get_last_valid_date()} 23:59:59")

		running = [row.previous_price for row in self.items if row.previous_price]
		if running:
			frappe.db.set_value(
				"Loan Security Price",
				{"name": ("in", running)},
				"valid_upto",
				add_to_date(valid_from, seconds=-1),
			)

		for row in self.items:
			price = frappe.get_doc(
				{
					"doctype": "Loan Security Price",
					"loan_security": row.loan_security,
					"loan_security_price": row.price,
					"valid_from": valid_from,
					"valid_upto": valid_upto,
					"price_update": self.name,
				}
			)
			price.flags.skip_sanctioned_limit_update = True
			price.insert(ignore_permissions=True)

	def restore_previous_prices(self):
		for row in self.items:
			if not (row.previous_price and frappe.db.exists("Loan Security Price", row.previous_price)):
				continue
			# A price entered after this update must stay the only one valid from its start
			next_price = frappe.db.get_value(
				"Loan Security Price",
				{"loan_security": row.loan_security, "valid_from": (">=", get_datetime(self.price_date))},
				["valid_from", "price_update"],
				order_by="valid_from asc",
				as_dict=True,
			)
			valid_upto = get_datetime(row.previous_valid_upto)
			if next_price:
				valid_upto = min(valid_upto, add_to_date(next_price.valid_from, seconds=-1))
				if next_price.price_update:
					# That update now ends the restored price, so its own cancel must restore it in full
					self.hand_over_previous_price(next_price.price_update, row)
			frappe.db.set_value("Loan Security Price", row.previous_price, "valid_upto", valid_upto)

	def hand_over_previous_price(self, price_update, row):
		item = frappe.qb.DocType("Loan Security Price Update Item")
		(
			frappe.qb.update(item)
			.set(item.previous_price, row.previous_price)
			.set(item.previous_valid_upto, row.previous_valid_upto)
			.where(item.parent == price_update)
			.where(item.loan_security == row.loan_security)
		).run()

	def set_previous_prices(self):
		# One query for every row: a price from the update date on is refused, and the price
		# still running on it is ended at submit and restored on cancel
		valid_from = get_datetime(self.price_date)
		securities = sorted({row.loan_security for row in self.items})
		# A second update of the same securities waits here, then its locking read sees this one's prices
		lock_loan_securities(securities)
		price_doctype = frappe.qb.DocType("Loan Security Price")
		prices = (
			frappe.qb.from_(price_doctype)
			.select(
				price_doctype.name,
				price_doctype.loan_security,
				price_doctype.valid_from,
				price_doctype.valid_upto,
			)
			.where(price_doctype.loan_security.isin(securities))
			.where(price_doctype.valid_upto >= valid_from)
			.orderby(price_doctype.valid_from)
			.for_update()
			.run(as_dict=True)
		)

		later, running = {}, {}
		for price in prices:
			if price.valid_from >= valid_from:
				later.setdefault(price.loan_security, price)
			else:
				running[price.loan_security] = price

		for row in self.items:
			if later_price := later.get(row.loan_security):
				frappe.throw(
					_(
						"Row {0}: Loan Security {1} already has price {2} from {3}. Cancel or delete it before you submit this update"
					).format(
						row.idx,
						frappe.bold(row.loan_security),
						frappe.bold(later_price.name),
						later_price.valid_from,
					)
				)

			previous = running.get(row.loan_security)
			row.previous_price = previous.name if previous else None
			row.previous_valid_upto = previous.valid_upto if previous else None

	def get_last_valid_date(self):
		validity_days = max(
			cint(frappe.db.get_value("Loan Security Type", self.loan_security_type, "price_validity_days")),
			1,
		)
		return add_days(add_working_days(self.price_date, validity_days, self.holiday_list), -1)

	def get_pledged_securities(self):
		pledge = frappe.qb.DocType("Pledge")
		assignment = frappe.qb.DocType("Loan Security Assignment")
		security = frappe.qb.DocType("Loan Security")

		return set(
			frappe.qb.from_(pledge)
			.inner_join(assignment)
			.on(pledge.parent == assignment.name)
			.inner_join(security)
			.on(pledge.loan_security == security.name)
			.select(pledge.loan_security)
			.distinct()
			.where(assignment.docstatus == 1)
			.where(assignment.status == "Pledged")
			.where(security.loan_security_type == self.loan_security_type)
			.where(security.disabled == 0)
			.run(pluck=True)
		)


def run_shortfall_check():
	frappe.enqueue(SHORTFALL_JOB, queue="long", enqueue_after_commit=True)
