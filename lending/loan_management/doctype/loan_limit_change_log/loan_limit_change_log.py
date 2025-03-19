# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LoanLimitChangeLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		change_date: DF.Date | None
		event: DF.Literal["Loan Booking", "Limit Renewal", "Disbursement", "Repayment"]
		loan: DF.Link | None
		value_change: DF.Currency
		value_type: DF.Literal["Maximum Limit Amount", "Utilized Limit Amount", "Available Limit Amount"]
	# end: auto-generated types

	pass


def create_loan_limit_change_log(**kwargs):
	loan_limit_change_log = frappe.new_doc("Loan Limit Change Log")
	loan_limit_change_log.update(kwargs)
	loan_limit_change_log.save(ignore_permissions=True)
