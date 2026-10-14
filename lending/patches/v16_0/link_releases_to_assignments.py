import frappe
from frappe.utils import flt

from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	allocate,
	get_candidate_assignments,
	get_unpledge_fields,
	get_unreleased_qty,
)


def execute():
	# Release rows now name the assignment they free. Link existing rows to the oldest pledges
	# of their security, as a new release does, so those pledges cannot be cancelled while the
	# release still subtracts their shares.
	fields = get_unpledge_fields()
	releases = frappe.get_all(
		"Loan Security Release",
		filters={"docstatus": 1},
		fields=["name", "applicant_type", "applicant", "loan"],
		order_by="creation asc",
	)

	for release in releases:
		rows = frappe.get_all(
			"Unpledge",
			filters={"parent": release.name, "parenttype": "Loan Security Release"},
			fields=["name", "idx", *fields],
			order_by="idx asc",
		)
		if all(row.loan_security_assignment for row in rows):
			continue

		candidates = get_candidate_assignments(release.loan, release.applicant_type, release.applicant)
		unreleased = get_unreleased_qty(candidates)
		next_idx = max(row.idx for row in rows) + 1

		for row in rows:
			if row.loan_security_assignment:
				continue

			pieces, remaining = allocate(flt(row.qty), row.loan_security, candidates, unreleased)
			if not pieces:
				continue
			if remaining > 0:
				pieces.append((None, remaining))

			first, *rest = pieces
			frappe.db.set_value(
				"Unpledge",
				row.name,
				{"loan_security_assignment": first[0], "qty": first[1]},
				update_modified=False,
			)
			for assignment, qty in rest:
				piece = frappe.get_doc(
					{
						**{field: row.get(field) for field in fields},
						"doctype": "Unpledge",
						"parent": release.name,
						"parenttype": "Loan Security Release",
						"parentfield": "securities",
						"idx": next_idx,
						"docstatus": 1,
						"qty": qty,
						"loan_security_assignment": assignment,
					}
				)
				piece.db_insert()
				next_idx += 1
