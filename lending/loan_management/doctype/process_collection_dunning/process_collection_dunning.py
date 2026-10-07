# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate


class ProcessCollectionDunning(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		company: DF.Link | None
		loan: DF.Link | None
		loan_product: DF.Link | None
		posting_date: DF.Date
	# end: auto-generated types

	def on_submit(self):
		from lending.loan_management.collections import process_collection_dunning_batch

		filters = {"status": ("not in", ["Resolved", "Closed"])}

		if self.loan:
			filters["loan"] = self.loan
		if self.company:
			filters["company"] = self.company
		if self.loan_product:
			filters["loan_product"] = self.loan_product

		open_cases = frappe.get_all("Collection Case", filters=filters, pluck="name")

		if self.loan:
			process_collection_dunning_batch(open_cases, self.name)
		else:
			BATCH_SIZE = 5000
			for i in range(0, len(open_cases), BATCH_SIZE):
				batch = open_cases[i : i + BATCH_SIZE]
				frappe.enqueue(
					process_collection_dunning_batch,
					collection_cases=batch,
					process_collection_dunning=self.name,
					queue="long",
					enqueue_after_commit=True,
				)

	def on_cancel(self):
		self.ignore_linked_doctypes = ["Collection Case Log"]


def create_process_collection_dunning(posting_date=None, loan_product=None, loan=None, company=None):
	posting_date = posting_date or add_days(getdate(), -1)
	process = frappe.new_doc("Process Collection Dunning")
	process.posting_date = posting_date
	process.loan_product = loan_product
	process.loan = loan
	process.company = company
	process.submit()
	return process.name
