import frappe
from frappe.utils import flt

from lending.loan_management.doctype.loan_security_release.loan_security_release import (
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

		candidates = get_candidates(release)
		unreleased = get_unreleased_qty(candidates)
		next_idx = max(row.idx for row in rows) + 1

		for row in rows:
			if row.loan_security_assignment:
				continue

			pieces, remaining = [], flt(row.qty)
			for name in candidates:
				free = flt(unreleased.get((name, row.loan_security)))
				if remaining <= 0:
					break
				if free <= 0:
					continue
				qty = min(free, remaining)
				pieces.append((name, qty))
				unreleased[(name, row.loan_security)] -= qty
				remaining -= qty

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


def get_candidates(release):
	filters = {"docstatus": 1, "status": "Pledged"}
	if release.loan:
		filters["loan"] = release.loan
	else:
		filters.update({"applicant_type": release.applicant_type, "applicant": release.applicant})

	return frappe.get_all(
		"Loan Security Assignment", filters=filters, order_by="pledge_time asc, creation asc", pluck="name"
	)
