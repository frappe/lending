# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanRestructureCharges(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		balance_charges: DF.Currency
		charge: DF.Link | None
		charges_overdue: DF.Currency
		loan_demand: DF.Link | None
		other_charges_waiver: DF.Currency
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		treatment_of_other_charges: DF.Literal["Capitalize", "Carry Forward"]
	# end: auto-generated types

	pass
