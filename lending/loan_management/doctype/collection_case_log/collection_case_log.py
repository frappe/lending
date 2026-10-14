# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class CollectionCaseLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		collection_case: DF.Link
		days_past_due: DF.Int
		event: DF.Literal[
			"Case Opened",
			"Bucket Escalated",
			"Dunning Sent",
			"Promise to Pay Captured",
			"Promise to Pay Broken",
			"Hardship Requested",
			"Resolved",
		]
		from_bucket: DF.Data | None
		loan: DF.Link
		posting_date: DF.Date
		process_collection_dunning: DF.Link | None
		to_bucket: DF.Data
	# end: auto-generated types

	pass
