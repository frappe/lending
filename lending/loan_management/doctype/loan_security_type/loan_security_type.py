# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


# import frappe
from frappe.model.document import Document


class LoanSecurityType(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		disabled: DF.Check
		haircut: DF.Percent
		loan_security_type: DF.Data
		loan_to_value_ratio: DF.Percent
		max_coin_weight: DF.Float
		max_ornament_weight: DF.Float
		metal: DF.Literal["", "Gold", "Silver"]
		track_lien: DF.Check
	# end: auto-generated types

	pass
