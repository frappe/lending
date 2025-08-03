# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class LoanAccrualRepost(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_accrual_repost_detail.loan_accrual_repost_detail import (
			LoanAccrualRepostDetail,
		)

		amended_from: DF.Link | None
		end_date: DF.Date | None
		start_date: DF.Date | None
		table_zwxp: DF.Table[LoanAccrualRepostDetail]
	# end: auto-generated types

	def on_submit(self):
		if len(self.get("loans")) > 10:
			frappe.enqueue(self.repost_interest_accruals, queue="long")
		else:
			self.repost_interest_accruals()

	def repost_interest_accruals(self):
		for loan in self.get("loans"):
			loan_status = frappe.db.get_value("Loan", loan.loan, "status")
			if loan_status in ("Written Off", "Settled"):
				written_off_date = frappe.db.get_value(
					"Loan Write Off", {"loan": loan.loan, "is_settlement_write_off": 0}, "written_off_date"
				)
				if not written_off_date:
					interest_accruals = self.get_interest_accrual_entries(loan.loan)
					for entry in interest_accruals:
						gl_exists = frappe.db.exists(
							"GL Entry",
							{"voucher_no": entry.name, "voucher_type": "Loan Interest Accrual", "is_cancelled": 0},
						)

						if not gl_exists and getdate(entry.posting_date) < getdate(written_off_date):
							doc = frappe.get_doc("Loan Interest Accrual", entry.name)
							doc.make_gl_entries()
						elif gl_exists and getdate(entry.posting_date) >= getdate(written_off_date):
							doc = frappe.get_doc("Loan Interest Accrual", entry.name)
							doc.make_gl_entries(cancel=True)
			elif loan_status in ("Disbursed", "Active"):
				interest_accruals = self.get_interest_accrual_entries(loan.loan)
				for entry in interest_accruals:
					gl_exists = frappe.db.exists(
						"GL Entry",
						{"voucher_no": entry.name, "voucher_type": "Loan Interest Accrual", "is_cancelled": 0},
					)

					if not gl_exists:
						doc = frappe.get_doc("Loan Interest Accrual", entry.name)
						doc.make_gl_entries()

	def get_interest_accrual_entries(self, loan):
		interest_accruals = frappe.get_all(
			"Loan Interest Accrual",
			filters={
				"loan": loan,
				"posting_date": ["between", [self.from_date, self.to_date]],
				"interest_type": "Normal Interest",
				"docstatus": 1,
			},
			fields=["name", "posting_date"],
		)

		return interest_accruals
