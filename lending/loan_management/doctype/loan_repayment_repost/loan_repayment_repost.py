# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, get_datetime, getdate

from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	calculate_amounts,
	get_pending_principal_amount,
)


class LoanRepaymentRepost(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_repayment_repost_cancel_detail.loan_repayment_repost_cancel_detail import (
			LoanRepaymentRepostCancelDetail,
		)
		from lending.loan_management.doctype.loan_repayment_repost_detail.loan_repayment_repost_detail import (
			LoanRepaymentRepostDetail,
		)

		amended_from: DF.Link | None
		cancel_future_accruals_and_demands: DF.Check
		cancel_future_emi_demands: DF.Check
		clear_demand_allocation_before_repost: DF.Check
		delete_gl_entries: DF.Check
		entries_to_cancel: DF.Table[LoanRepaymentRepostCancelDetail]
		ignore_on_cancel_amount_update: DF.Check
		loan: DF.Link
		loan_disbursement: DF.Link | None
		recalculate_allocated_charges: DF.Check
		repayment_entries: DF.Table[LoanRepaymentRepostDetail]
		repost_date: DF.Date
	# end: auto-generated types

	def validate(self):
		self.get_repayment_entries()

	def get_repayment_entries(self):
		self.set("repayment_entries", [])
		filters = {
			"against_loan": self.loan,
			"docstatus": 1,
			"posting_date": (">=", self.repost_date),
		}

		if self.loan_disbursement:
			filters["loan_disbursement"] = self.loan_disbursement

		entries = frappe.get_all(
			"Loan Repayment", filters, ["name", "posting_date"], order_by="posting_date desc, creation desc"
		)
		for entry in entries:
			self.append(
				"repayment_entries",
				{
					"loan_repayment": entry.name,
					"posting_date": entry.posting_date,
				},
			)

	def on_submit(self):
		if self.clear_demand_allocation_before_repost:
			self.clear_demand_allocation()

		self.trigger_on_cancel_events()
		if self.recalculate_allocated_charges:
			self.loan_demands_to_be_corrected = set()
			self.loan_demands_to_be_corrected.update(
				self.recalculate_allocated_demands(
					[entry.loan_repayment for entry in self.get("repayment_entries")]
				)
			)
		self.cancel_demands()
		self.trigger_on_submit_events()

	def cancel_demands(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import reverse_demands
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)

		if self.cancel_future_emi_demands:
			reverse_demands(
				self.loan, self.repost_date, demand_type="EMI", loan_disbursement=self.loan_disbursement
			)

		if self.cancel_future_accruals_and_demands:
			reverse_loan_interest_accruals(
				self.loan,
				self.repost_date,
				loan_disbursement=self.loan_disbursement,
			)
			reverse_demands(
				self.loan, self.repost_date, demand_type="Penalty", loan_disbursement=self.loan_disbursement
			)

	def clear_demand_allocation(self):
		demands = frappe.get_all(
			"Loan Demand",
			{
				"loan": self.loan,
				"docstatus": 1,
				"demand_type": "EMI",
				"demand_date": (">=", self.repost_date),
			},
			["name", "demand_amount"],
		)

		for demand in demands:
			frappe.db.set_value(
				"Loan Demand",
				demand.name,
				{
					"paid_amount": 0,
					"outstanding_amount": demand.demand_amount,
				},
			)

		for entry in self.get("repayment_entries"):
			repayment_doc = frappe.get_doc("Loan Repayment", entry.loan_repayment)
			for repayment_detail in repayment_doc.get("repayment_details"):
				if repayment_detail.demand_type == "EMI":
					frappe.delete_doc("Loan Repayment Detail", repayment_detail.name, force=1)

	def trigger_on_cancel_events(self):
		entries_to_cancel = [d.loan_repayment for d in self.get("entries_to_cancel")]
		for entry in self.get("repayment_entries"):
			repayment_doc = frappe.get_doc("Loan Repayment", entry.loan_repayment)
			if entry.loan_repayment in entries_to_cancel:
				repayment_doc.flags.ignore_links = True
				repayment_doc.flags.from_repost = True
				repayment_doc.cancel()
				repayment_doc.flags.from_repost = False
			else:
				repayment_doc.docstatus = 2

				repayment_doc.update_demands(cancel=1)
				repayment_doc.update_security_deposit_amount(cancel=1)

				if repayment_doc.repayment_type in ("Advance Payment", "Pre Payment"):
					repayment_doc.cancel_loan_restructure()

				if self.delete_gl_entries:
					frappe.db.sql(
						"DELETE FROM `tabGL Entry` WHERE voucher_type='Loan Repayment' AND voucher_no=%s",
						repayment_doc.name,
					)
				else:
					# cancel GL Entries
					repayment_doc.make_gl_entries(cancel=1)

			filters = {"against_loan": self.loan, "docstatus": 1, "posting_date": ("<", self.repost_date)}

			totals = frappe.db.get_value(
				"Loan Repayment",
				filters,
				[
					"SUM(principal_amount_paid) as total_principal_paid",
					"SUM(amount_paid) as total_amount_paid",
				],
				as_dict=1,
			)

			frappe.db.set_value(
				"Loan",
				self.loan,
				{
					"total_principal_paid": flt(totals.total_principal_paid),
					"total_amount_paid": flt(totals.total_amount_paid),
					"excess_amount_paid": 0,
				},
			)

			if self.loan_disbursement:
				total_principal_paid = frappe.db.get_value(
					"Loan Repayment",
					{
						"against_loan": self.loan,
						"loan_disbursement": self.loan_disbursement,
						"docstatus": 1,
						"posting_date": ("<", self.repost_date),
					},
					"sum(principal_amount_paid)",
				)

				frappe.db.set_value(
					"Loan Disbursement",
					self.loan_disbursement,
					"principal_amount_paid",
					flt(total_principal_paid),
				)

	def trigger_on_submit_events(self):
		from lending.loan_management.doctype.loan_repayment.loan_repayment import (
			update_installment_counts,
		)
		from lending.loan_management.doctype.loan_restructure.loan_restructure import (
			create_update_loan_reschedule,
		)
		from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
			create_process_loan_classification,
		)

		entries_to_cancel = [d.loan_repayment for d in self.get("entries_to_cancel")]

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		for entry in reversed(self.get("repayment_entries", [])):
			if entry.loan_repayment in entries_to_cancel:
				continue

			frappe.flags.on_repost = True

			frappe.get_doc(
				{
					"doctype": "Process Loan Interest Accrual",
					"loan": self.loan,
					"posting_date": entry.posting_date,
					"loan_disbursement": self.loan_disbursement,
				}
			).submit()

			frappe.get_doc(
				{
					"doctype": "Process Loan Demand",
					"loan": self.loan,
					"posting_date": entry.posting_date,
					"loan_disbursement": self.loan_disbursement,
				}
			).submit()

			repayment_doc = frappe.get_doc("Loan Repayment", entry.loan_repayment)
			repayment_doc.flags.from_repost = True

			for entry in repayment_doc.get("repayment_details"):
				frappe.delete_doc("Loan Repayment Detail", entry.name, force=1)

			repayment_doc.docstatus = 1
			repayment_doc.set("pending_principal_amount", 0)
			repayment_doc.set("excess_amount", 0)

			charges = []
			if self.get("payable_charges"):
				charges = [d.get("charge_code") for d in self.get("payable_charges")]

			amounts = calculate_amounts(
				repayment_doc.against_loan,
				repayment_doc.posting_date,
				payment_type=repayment_doc.repayment_type,
				charges=charges,
				loan_disbursement=repayment_doc.loan_disbursement,
				for_update=True,
			)
			repayment_doc.set_missing_values(amounts)

			loan = frappe.get_doc("Loan", repayment_doc.against_loan)
			pending_principal_amount = get_pending_principal_amount(
				loan, loan_disbursement=self.loan_disbursement
			)

			repayment_doc.set("pending_principal_amount", flt(pending_principal_amount, precision))
			repayment_doc.run_method("before_validate")

			repayment_doc.allocate_amount_against_demands(amounts, on_submit=True)
			if self.recalculate_allocated_charges:
				while True:
					new_allocations = {i.loan_demand for i in repayment_doc.get("repayment_details")}
					repayment_doc.allocate_amount_against_demands(amounts, on_submit=True)
					if len(new_allocations.difference(self.loan_demands_to_be_corrected)):
						self.loan_demands_to_be_corrected.update(
							self.recalculate_allocated_demands([repayment_doc.name])
						)
					else:
						break

			if repayment_doc.repayment_type in ("Advance Payment", "Pre Payment") and (
				not repayment_doc.principal_amount_paid >= repayment_doc.pending_principal_amount
			):
				create_update_loan_reschedule(
					repayment_doc.against_loan,
					repayment_doc.posting_date,
					repayment_doc.name,
					repayment_doc.repayment_type,
					repayment_doc.principal_amount_paid,
					loan_disbursement=repayment_doc.loan_disbursement,
				)

				repayment_doc.reverse_future_accruals_and_demands()
				repayment_doc.process_reschedule()

			if repayment_doc.repayment_type not in ("Advance Payment", "Pre Payment") or (
				repayment_doc.principal_amount_paid >= repayment_doc.pending_principal_amount
			):
				repayment_doc.book_interest_accrued_not_demanded()
				if repayment_doc.is_term_loan:
					repayment_doc.book_pending_principal()

			# Run on_submit events
			repayment_doc.update_paid_amounts()
			repayment_doc.handle_auto_demand_write_off()
			repayment_doc.update_demands()
			repayment_doc.update_security_deposit_amount()
			repayment_doc.db_update_all()
			repayment_doc.make_gl_entries()

			update_installment_counts(self.loan)

			if repayment_doc.repayment_type == "Full Settlement":
				loan_write_off = frappe.db.get_value(
					"Loan Write Off",
					{"loan": self.loan, "docstatus": 1, "is_settlement_write_off": 1},
					["name", "write_off_amount"],
					as_dict=1,
				)

				if loan_write_off:
					write_off_amount = flt(
						repayment_doc.payable_principal_amount - repayment_doc.principal_amount_paid, 2
					)
					if flt(loan_write_off.write_off_amount, 2) != write_off_amount:
						doc = frappe.get_doc("Loan Write Off", loan_write_off.name)
						doc.make_gl_entries(cancel=1)

						frappe.db.set_value(
							"Loan Write Off", loan_write_off.name, "write_off_amount", write_off_amount
						)
						doc.load_from_db()
						doc.make_gl_entries()

					frappe.db.set_value("Loan", self.loan, "written_off_amount", write_off_amount)

			repayment_doc.flags.from_repost = False
			frappe.flags.on_repost = False

		frappe.get_doc(
			{
				"doctype": "Process Loan Interest Accrual",
				"loan": self.loan,
				"posting_date": getdate(),
				"loan_disbursement": self.loan_disbursement,
			}
		).submit()

		frappe.get_doc(
			{
				"doctype": "Process Loan Demand",
				"loan": self.loan,
				"posting_date": getdate(),
				"loan_disbursement": self.loan_disbursement,
			}
		).submit()

		loan = frappe.db.get_value("Loan", self.loan, "status")
		if loan == "Closed":
			create_process_loan_classification(
				posting_date=self.repost_date,
				loan=self.loan,
				loan_disbursement=self.loan_disbursement,
			)

	def recalculate_allocated_demands(self, loan_repayments):
		# gets all the demands for the repayment, goes back, and recalculates
		# the outstanding and paid amounts up until the reposting date
		repayment_details = frappe.qb.DocType("Loan Repayment Detail")

		# get all child tables from the loan_repayments
		query = (
			frappe.qb.from_(repayment_details)
			.where(repayment_details.parent.isin(loan_repayments))
			.where(repayment_details.demand_type == "Charges")
			.select(repayment_details.loan_demand)
		)

		loan_demands_to_be_corrected = {i[0] for i in query.run(as_list=True)}.difference(
			self.loan_demands_to_be_corrected
		)

		if len(loan_demands_to_be_corrected) == 0:
			return set()
		repayment = frappe.qb.DocType("Loan Repayment")
		query = (
			frappe.qb.from_(repayment)
			.join(repayment_details)
			.on(repayment_details.parent == repayment.name)
			.where(repayment.docstatus == 1)
			.where(repayment.posting_date < get_datetime(self.repost_date))
			.where(repayment_details.loan_demand.isin(loan_demands_to_be_corrected))
			.select(repayment_details.loan_demand, Sum(repayment_details.paid_amount).as_("paid_amount"))
			.groupby(repayment_details.loan_demand)
		)

		# separate queries for waived off and repaid amounts
		query1 = query.where(
			repayment.repayment_type.notin(["Interest Waiver", "Penalty Waiver", "Charges Waiver"])
		)
		paid_amounts = {i.loan_demand: i.paid_amount for i in query1.run(as_dict=True)}
		query2 = query.where(
			repayment.repayment_type.isin(["Interest Waiver", "Penalty Waiver", "Charges Waiver"])
		)
		waived_amounts = {i.loan_demand: i.paid_amount for i in query2.run(as_dict=True)}

		for loan_demand in loan_demands_to_be_corrected:
			demand_amount = frappe.db.get_value("Loan Demand", loan_demand, "demand_amount")
			paid_amount = 0
			waived_amount = 0
			if loan_demand in paid_amounts:
				paid_amount += paid_amounts[loan_demand]
			if loan_demand in waived_amounts:
				waived_amount += waived_amounts[loan_demand]

			if paid_amount + waived_amount > demand_amount:
				frappe.throw(
					_(
						"There are problems with the allocation amounts before this reposting date (Demand Amount: {0}, Paid Amount: {1}, Waived Amount: {2})"
					).format(demand_amount, paid_amount, waived_amount)
				)
			else:
				# set amounts
				frappe.db.set_value("Loan Demand", loan_demand, "paid_amount", paid_amount)
				frappe.db.set_value("Loan Demand", loan_demand, "waived_amount", waived_amount)
				frappe.db.set_value(
					"Loan Demand", loan_demand, "outstanding_amount", demand_amount - waived_amount - paid_amount
				)
		return loan_demands_to_be_corrected
