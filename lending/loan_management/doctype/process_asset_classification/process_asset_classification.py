# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class ProcessAssetClassification(Document):
	def on_submit(self):
		from erpnext.loan_management.doctype.loan.loan import update_days_past_due_in_loans

		update_days_past_due_in_loans(
			posting_date=self.posting_date,
			loan_type=self.loan_type,
			loan_name=self.loan,
			process_asset_classification=self.name,
		)


def create_process_asset_classification(
	posting_date=None, loan_type=None, loan=None, payment_reference=None
):
	posting_date = posting_date or getdate()

	previous_process = frappe.db.get_all(
		"Process Asset Classification",
		filters={"posting_date": ("<=", posting_date), "loan": ("in", ["", loan])},
		fields=["name"],
		order_by="posting_date desc",
		limit=1,
	)

	asset_classification = frappe.new_doc("Process Asset Classification")
	asset_classification.posting_date = posting_date
	asset_classification.loan_type = loan_type
	asset_classification.loan = loan
	asset_classification.previous_process = previous_process[0].name if previous_process else None
	asset_classification.payment_reference = payment_reference
	asset_classification.submit()