# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LOSSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		unique_customer: DF.Check
	# end: auto-generated types

	pass

	def on_update(self):
		fields = ["mobile_no", "email_id"]
		field_string = ", ".join([f"'{i}'" for i in fields])  # for raw sql querying

		fields_with_unique_constraints = frappe.db.sql(
			f"""
															select column_name
															from information_schema.statistics
															where table_name='tabCustomer'
															and column_name in ({field_string})
															and non_unique = 0
														"""
		)
		fields_with_unique_constraints = [i[0] for i in fields_with_unique_constraints]
		if self.unique_customer:
			# for field in fields_with_unique_constraints
			for field in set(fields).difference(set(fields_with_unique_constraints)):
				frappe.db.add_unique("Customer", field)
		else:
			frappe.enqueue(
				remove_unique_constraints, fields_with_unique_constraints=fields_with_unique_constraints
			)


def remove_unique_constraints(fields_with_unique_constraints):
	for field in fields_with_unique_constraints:
		frappe.db.sql(f"""alter table tabCustomer drop index unique_{field}""")
