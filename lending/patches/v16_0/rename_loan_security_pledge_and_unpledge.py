# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.utils import now_datetime

RENAMES = {
	"Loan Security Pledge": "Loan Security Assignment",
	"Loan Security Unpledge": "Loan Security Release",
}


def execute():
	for old_name, new_name in RENAMES.items():
		if not frappe.db.exists("DocType", old_name) or frappe.db.exists("DocType", new_name):
			continue

		prepare_table_for_rename(old_name, new_name)
		frappe.rename_doc("DocType", old_name, new_name, force=True)


def prepare_table_for_rename(old_name, new_name):
	# A failed migrate or a restore can leave the new table behind while the DocType still has
	# the old name. The rename fails if the new table exists, so make the name free. No rows are lost.
	old_table = f"tab{old_name}"
	new_table = f"tab{new_name}"

	if not frappe.db.table_exists(new_name, cached=False):
		return

	if not frappe.db.table_exists(old_name, cached=False):
		frappe.db.sql_ddl(f"RENAME TABLE `{new_table}` TO `{old_table}`")
	elif frappe.qb.from_(frappe.qb.DocType(new_name)).select(1).limit(1).run():
		backup_table = f"{new_table}_backup_{now_datetime().strftime('%Y%m%d%H%M%S')}"
		frappe.db.sql_ddl(f"RENAME TABLE `{new_table}` TO `{backup_table}`")
	else:
		frappe.db.sql_ddl(f"DROP TABLE `{new_table}`")
