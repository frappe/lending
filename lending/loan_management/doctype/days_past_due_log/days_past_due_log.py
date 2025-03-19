# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class DaysPastDueLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		days_past_due: DF.Int
		loan: DF.Link | None
		loan_disbursement: DF.Link | None
		posting_date: DF.Date | None
		process_loan_classification: DF.Link | None
	# end: auto-generated types

	pass
