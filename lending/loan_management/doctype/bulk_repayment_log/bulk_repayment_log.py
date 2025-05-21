# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class BulkRepaymentLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		details: DF.LongText | None
		loan: DF.Link | None
		status: DF.Data | None
		timestamp: DF.Datetime | None
		traceback: DF.LongText | None
	# end: auto-generated types

	pass
