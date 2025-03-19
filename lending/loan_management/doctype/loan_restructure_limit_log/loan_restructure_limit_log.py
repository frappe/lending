# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanRestructureLimitLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		available_limit: DF.Currency
		branch: DF.Link | None
		company: DF.Link | None
		date: DF.Date | None
		delinquent_available_limit: DF.Currency
		delinquent_in_process_limit: DF.Currency
		delinquent_limit_amount: DF.Currency
		delinquent_limit_percent: DF.Percent
		delinquent_principal_outstanding: DF.Currency
		delinquent_utilized_limit: DF.Currency
		in_process_limit: DF.Currency
		limit_amount: DF.Currency
		limit_percent: DF.Percent
		principal_outstanding: DF.Currency
		utilized_limit: DF.Currency
	# end: auto-generated types

	pass
