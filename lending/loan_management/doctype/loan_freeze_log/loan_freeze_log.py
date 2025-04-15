# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanFreezeLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		freeze_date: DF.Date | None
		loan: DF.Link | None
		reason_for_freezing: DF.SmallText | None
		unfreeze_date: DF.Date | None
	# end: auto-generated types

	pass
