# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from lending.loan_management.collections import get_applicant_email
from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price_map,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
	update_sanctioned_loan_amount_for_applicant,
)
from lending.loan_management.doctype.loan_security_sale.proceeds import SaleProceeds
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	get_ltv_ratio_map,
)


class LoanSecuritySale(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_security_sale_item.loan_security_sale_item import (
			LoanSecuritySaleItem,
		)
		from lending.loan_management.doctype.loan_security_sale_repayment.loan_security_sale_repayment import (
			LoanSecuritySaleRepayment,
		)

		amended_from: DF.Link | None
		amount_to_recover: DF.Currency
		applicant: DF.DynamicLink | None
		applicant_email: DF.Data | None
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		charge_voucher: DF.DynamicLink | None
		charge_voucher_type: DF.Link | None
		charges: DF.Currency
		company: DF.Link | None
		gross_proceeds: DF.Currency
		items: DF.Table[LoanSecuritySaleItem]
		loan: DF.Link
		loan_security_shortfall: DF.Link | None
		net_proceeds: DF.Currency
		posting_date: DF.Date
		reason: DF.Literal["Margin Call Not Cured", "Loan Default", "Borrower Request"]
		repayments: DF.Table[LoanSecuritySaleRepayment]
		status: DF.Literal["Draft", "Sold", "Proceeds Applied", "Cancelled"]
		surplus_amount: DF.Currency
	# end: auto-generated types

	def validate(self):
		if self.docstatus == 0:
			self.status = "Draft"
			self.set_amount_to_recover()
			self.applicant_email = get_applicant_email(self.applicant_type, self.applicant)
		self.validate_items()
		self.set_proceeds()

	def before_submit(self):
		self.validate_sold_items()
		self.validate_shortfall_open()
		if flt(self.charges) and not frappe.db.get_single_value("Lending Settings", "sale_charge"):
			frappe.throw(_("Set the Sale Charge in Lending Settings to charge a fee on the sale"))

	def on_submit(self):
		self.db_set("status", "Sold")
		self.update_assignment_status()
		update_sanctioned_loan_amount_for_applicant(self.applicant, self.applicant_type)
		if self.loan_security_shortfall:
			self.trigger_shortfall_sale()

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		# The submitted sale links to its repayments and charge, so none can be cancelled before it
		for row in reversed(self.repayments):
			self.cancel_linked("Loan Repayment", row.loan_repayment)
		self.cancel_linked(self.charge_voucher_type, self.charge_voucher)
		self.update_assignment_status()
		update_sanctioned_loan_amount_for_applicant(self.applicant, self.applicant_type)

	def cancel_linked(self, doctype, name):
		if name and frappe.db.get_value(doctype, name, "docstatus") == 1:
			frappe.get_doc(doctype, name).cancel()

	@frappe.whitelist()
	def prefill_items(self):
		"""Pick the largest holdings first until their expected proceeds cover the amount to recover."""
		self.set_amount_to_recover()
		pledged_qty_map = get_pledged_security_qty(loan=self.loan)
		price_map = get_loan_security_price_map(list(pledged_qty_map))
		cover_map = self.get_cover_per_unit(price_map)

		holdings = sorted(
			(
				(security, flt(qty), flt(price_map.get(security)))
				for security, qty in pledged_qty_map.items()
				if flt(qty) > 0 and cover_map.get(security, 0) > 0
			),
			key=lambda holding: holding[1] * holding[2],
			reverse=True,
		)

		self.set("items", [])
		remaining = flt(self.amount_to_recover)
		for security, qty, price in holdings:
			if remaining <= 0:
				break
			sell_qty = min(qty, math.ceil(remaining / cover_map[security]))
			self.append(
				"items",
				{"loan_security": security, "pledged_qty": qty, "qty": sell_qty, "expected_price": price},
			)
			remaining -= sell_qty * cover_map[security]

	@frappe.whitelist()
	def apply_proceeds(self):
		# A locking read sees a parallel click's commit, and the reload drops any values the client sent
		status = frappe.db.get_value(self.doctype, self.name, "status", for_update=True)
		self.reload()
		self.check_permission("submit")
		frappe.has_permission("Loan Repayment", "create", throw=True)
		if self.docstatus != 1 or status != "Sold":
			frappe.throw(_("Only a sold Loan Security Sale can apply its proceeds"))

		surplus_amount = SaleProceeds(self).apply()
		self.db_set({"status": "Proceeds Applied", "surplus_amount": surplus_amount})

	def set_amount_to_recover(self):
		if flt(self.amount_to_recover) or not self.loan:
			return
		if self.loan_security_shortfall:
			self.amount_to_recover = frappe.db.get_value(
				"Loan Security Shortfall", self.loan_security_shortfall, "shortfall_amount"
			)
		else:
			self.amount_to_recover = calculate_amounts(
				self.loan, self.posting_date or nowdate(), payment_type="Loan Closure"
			)["payable_amount"]

	def get_cover_per_unit(self, price_map):
		# Selling a unit also removes its LTV share from the allowed amount, so it cures less than its price
		if not self.loan_security_shortfall:
			return {security: flt(price) for security, price in price_map.items()}
		ltv_ratio_map = get_ltv_ratio_map(list(price_map))
		return {
			security: flt(price) * (100 - flt(ltv_ratio_map.get(security))) / 100
			for security, price in price_map.items()
		}

	def validate_items(self):
		if self.docstatus == 1:
			frappe.db.get_value("Loan", self.loan, "name", for_update=True)

		pledged_qty_map = get_pledged_security_qty(loan=self.loan)
		price_map = get_loan_security_price_map([row.loan_security for row in self.items])
		listed = set()
		for row in self.items:
			if row.loan_security in listed:
				frappe.throw(
					_("Row {0}: Loan Security {1} is added more than once").format(
						row.idx, frappe.bold(row.loan_security)
					)
				)
			listed.add(row.loan_security)

			row.pledged_qty = flt(pledged_qty_map.get(row.loan_security))
			row.expected_price = flt(price_map.get(row.loan_security))
			if max(flt(row.qty), flt(row.sold_qty)) > row.pledged_qty:
				frappe.throw(
					_("Row {0}: Only {1} of Loan Security {2} is pledged against Loan {3}").format(
						row.idx, row.pledged_qty, frappe.bold(row.loan_security), frappe.bold(self.loan)
					)
				)

	def set_proceeds(self):
		for row in self.items:
			row.proceeds = flt(row.sold_qty) * flt(row.sale_price)
		self.gross_proceeds = sum(flt(row.proceeds) for row in self.items)
		self.net_proceeds = self.gross_proceeds - flt(self.charges)

	def validate_shortfall_open(self):
		if (
			self.loan_security_shortfall
			and frappe.db.get_value("Loan Security Shortfall", self.loan_security_shortfall, "status")
			== "Completed"
		):
			frappe.throw(
				_(
					"Loan Security Shortfall {0} is already cured. To record this sale anyway, clear the shortfall and pick another reason"
				).format(frappe.bold(self.loan_security_shortfall))
			)

	def trigger_shortfall_sale(self):
		status = frappe.db.get_value("Loan Security Shortfall", self.loan_security_shortfall, "status")
		if status in ("Pending", "Notified", "Escalated"):
			frappe.db.set_value(
				"Loan Security Shortfall", self.loan_security_shortfall, "status", "Sale Triggered"
			)

	def validate_sold_items(self):
		if not any(flt(row.sold_qty) > 0 for row in self.items):
			frappe.throw(_("Enter the sold qty and sale price of at least one security"))
		for row in self.items:
			if flt(row.sold_qty) > 0 and flt(row.sale_price) <= 0:
				frappe.throw(
					_("Row {0}: Enter the sale price of Loan Security {1}").format(
						row.idx, frappe.bold(row.loan_security)
					)
				)

	def update_assignment_status(self):
		"""An assignment is Repossessed once every security in it that this sale sold is gone from the loan."""
		sold = {row.loan_security for row in self.items if flt(row.sold_qty) > 0}
		pledged_qty_map = get_pledged_security_qty(loan=self.loan)
		assignments = frappe.get_all(
			"Loan Security Assignment",
			filters={"loan": self.loan, "docstatus": 1, "status": ("in", ["Pledged", "Repossessed"])},
			fields=["name", "status"],
		)
		for assignment in assignments:
			securities = set(frappe.get_all("Pledge", {"parent": assignment.name}, pluck="loan_security"))
			if not securities & sold:
				continue
			fully_sold = all(flt(pledged_qty_map.get(security)) <= 0 for security in securities)
			status = "Repossessed" if fully_sold else "Pledged"
			if status != assignment.status:
				frappe.db.set_value("Loan Security Assignment", assignment.name, "status", status)

