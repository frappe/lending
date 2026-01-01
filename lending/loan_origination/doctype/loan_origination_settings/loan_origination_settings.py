# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document

fields_that_can_have_unique_constraints = ["mobile_no", "email_id"]


class LoanOriginationSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		employee_loans: DF.Check
		unique_customer: DF.Check
	# end: auto-generated types

	pass

	def before_save(self):
		if self.unique_customer:
			add_unique_constraints()
		else:
			remove_unique_constraints()


def add_unique_constraints():
	fields_with_unique_constraints = get_fields_with_unique_constraints()

	# for field in fields_with_unique_constraints
	for field in set(fields_that_can_have_unique_constraints).difference(
		set(fields_with_unique_constraints)
	):
		try:
			frappe.db.add_unique("Customer", field)

		except Exception:
			# remove any added constraints
			remove_unique_constraints()


def remove_unique_constraints():
	fields_with_unique_constraints = get_fields_with_unique_constraints()
	for field in fields_with_unique_constraints:
		frappe.db.sql_ddl(f"""alter table tabCustomer drop index unique_{field}""")


def get_fields_with_unique_constraints():
	field_string = ", ".join(
		[f"'{i}'" for i in fields_that_can_have_unique_constraints]
	)  # for raw sql querying
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

	return fields_with_unique_constraints
