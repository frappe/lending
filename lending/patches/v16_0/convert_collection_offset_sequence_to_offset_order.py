import frappe

# EMI already pays interest and principal, so they are not added again (it would pay twice)
EMI_ORDER = (
	"EMI Offset Order",
	["EMI (Principal + Interest)", "Additional Interest", "Penalty", "Charges"],
)

FIELD_ORDER = {
	"collection_offset_sequence_for_standard_asset": EMI_ORDER,
	"collection_offset_sequence_for_sub_standard_asset": EMI_ORDER,
}


def execute():
	make_offset_order(*EMI_ORDER)

	for fieldname, (title, _) in FIELD_ORDER.items():
		make_field_a_link(fieldname)
		set_order_on_companies(fieldname, title)

	frappe.clear_cache(doctype="Company")


def make_offset_order(title, components):
	if frappe.db.exists("Loan Demand Offset Order", title):
		return

	doc = frappe.new_doc("Loan Demand Offset Order")
	doc.title = title
	for demand_type in components:
		doc.append("components", {"demand_type": demand_type})
	doc.insert(ignore_permissions=True)


def make_field_a_link(fieldname):
	# v15 had these as Select fields with text like "IP...IP...IP...CCC"
	frappe.db.set_value(
		"Custom Field",
		{"dt": "Company", "fieldname": fieldname},
		{"fieldtype": "Link", "options": "Loan Demand Offset Order"},
	)


def set_order_on_companies(fieldname, title):
	for company in frappe.get_all("Company", pluck="name"):
		current = frappe.db.get_value("Company", company, fieldname)
		# replace old text or empty value, keep a real order name
		if not frappe.db.exists("Loan Demand Offset Order", current or ""):
			frappe.db.set_value("Company", company, fieldname, title, update_modified=False)
