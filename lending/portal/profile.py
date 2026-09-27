# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The borrower's personal information page, and the one write it accepts.

One login can hold several Customer records -- PORTAL_PLAN.md section 7 -- so this
page shows a section per record rather than pretending there is one identity, and the
edit form names which record it is correcting.

Section 6.3 divides the fields in two. Contact details and address are the borrower's
to correct. Identity is not: the name on the record and the tax id behind it belong to
the verified file, and a borrower editing those would be editing the result of a KYC
check. save_profile enforces that split by writing a fixed list of fields and reading
nothing else from the request.
"""

import frappe
from frappe import _

from lending.portal.core import clean, get_loans, get_portal_customers, shell_payload

CUSTOMER_FIELDS = (
	"name",
	"customer_name",
	"customer_type",
	"tax_id",
	"mobile_no",
	"email_id",
	"customer_primary_contact",
	"customer_primary_address",
)

# What section 6.3 lets a borrower correct. Anything absent from these two lists is
# shown on the page but never read from the request, so adding a field to the form
# without adding it here changes nothing.
EDITABLE_CONTACT = ("email", "mobile", "phone")
EDITABLE_ADDRESS = (
	"address_line1",
	"address_line2",
	"city",
	"state",
	"pincode",
	"country",
)


@frappe.whitelist()
def get_profile_page() -> dict:
	"""Every customer record behind this login, with its contact details and address."""
	customers = get_portal_customers()
	loans = get_loans(customers) if customers else []

	records = []
	for name in customers:
		customer = frappe.db.get_value("Customer", name, CUSTOMER_FIELDS, as_dict=True)
		records.extend(identity_rows(customer))
		records.extend(contact_rows(customer))
		records.extend(address_rows(customer))

	payload = shell_payload(_("Personal details"), _("Contact us"), loans)
	payload.update(
		{
			"records": records,
			"records_note": (
				_("Across {0} profiles").format(len(customers))
				if len(customers) > 1
				else _("Your profile")
			),
			"edit_note": _(
				"Contact details and address can be corrected. Name and tax id come from "
				"your verified records — write to us to change those."
			),
		}
	)
	payload.update(edit_form(customers))

	return payload


def chosen_customer(customers: list[str]) -> str | None:
	"""Which record the form is editing. A name from the request must be one of ours."""
	asked = frappe.form_dict.get("customer")

	return asked if asked in customers else (customers[0] if customers else None)


def edit_form(customers: list[str]) -> dict:
	"""Current values for the edit form, so the boxes open filled in.

	`forms` holds every record's values, keyed by customer, so a page that switches
	between records can refill its boxes without asking again. The `form_*` keys are
	the chosen record's, flattened.
	"""
	name = chosen_customer(customers)
	if not name:
		return {"form_customer": "", "customer_options": [], "form_note": "", "forms": {}}

	forms = {row: record_values(row) for row in customers}
	chosen = forms[name]

	form = {
		"form_customer": name,
		"forms": forms,
		"customer_options": [
			{"label": values["customer_name"] or row, "value": row} for row, values in forms.items()
		],
		"form_note": _("Editing {0}").format(chosen["customer_name"]),
		"save_label": _("Save my details"),
	}
	form.update({f"form_{field}": chosen[field] for field in EDITABLE_CONTACT + EDITABLE_ADDRESS})

	return form


def record_values(name: str) -> dict:
	"""One record's identity, contact details and address, as the form's boxes read them."""
	customer = frappe.db.get_value("Customer", name, CUSTOMER_FIELDS, as_dict=True)
	contact = frappe.db.get_value(
		"Contact", primary_contact(customer), ["email_id", "mobile_no", "phone"], as_dict=True
	) or frappe._dict()
	address = frappe.db.get_value(
		"Address", primary_address(customer), EDITABLE_ADDRESS, as_dict=True
	) or frappe._dict()

	values = {
		"customer_name": customer.customer_name or "",
		"customer_type": customer.customer_type or "",
		"tax_id": customer.tax_id or "",
		"email": contact.email_id or customer.email_id or "",
		"mobile": contact.mobile_no or customer.mobile_no or "",
		"phone": contact.phone or "",
	}
	values.update({field: address.get(field) or "" for field in EDITABLE_ADDRESS})

	return values


def row(label: str, value: str, detail: str = "") -> dict:
	return {"label": label, "value": value or _("Not on record"), "detail": detail}


def identity_rows(customer: dict) -> list[dict]:
	return [
		row(_("Name"), customer.customer_name, customer.name),
		row(_("Registered as"), customer.customer_type),
		# tax_id is where an Indian install keeps the PAN or GSTIN. Read-only: it is the
		# outcome of a KYC check, not a preference.
		row(_("Tax id"), customer.tax_id),
	]


def primary_contact(customer: dict) -> str | None:
	"""The contact on the customer, or whichever contact links back to it.

	Customer.email_id and mobile_no are fetched from the primary contact rather than
	stored, so the contact is the record to read -- and later, to write.
	"""
	if customer.customer_primary_contact:
		return customer.customer_primary_contact

	links = frappe.get_all(
		"Contact",
		filters=[["Dynamic Link", "link_doctype", "=", "Customer"], ["Dynamic Link", "link_name", "=", customer.name]],
		pluck="name",
		limit=1,
	)

	return links[0] if links else None


def contact_rows(customer: dict) -> list[dict]:
	name = primary_contact(customer)
	if not name:
		return [row(_("Email"), customer.email_id), row(_("Mobile"), customer.mobile_no)]

	contact = frappe.db.get_value(
		"Contact", name, ["email_id", "mobile_no", "phone"], as_dict=True
	)

	return [
		row(_("Email"), contact.email_id or customer.email_id),
		row(_("Mobile"), contact.mobile_no or customer.mobile_no),
		row(_("Phone"), contact.phone),
	]


def primary_address(customer: dict) -> str | None:
	if customer.customer_primary_address:
		return customer.customer_primary_address

	links = frappe.get_all(
		"Address",
		filters=[["Dynamic Link", "link_doctype", "=", "Customer"], ["Dynamic Link", "link_name", "=", customer.name]],
		pluck="name",
		limit=1,
	)

	return links[0] if links else None


def address_rows(customer: dict) -> list[dict]:
	name = primary_address(customer)
	if not name:
		return [row(_("Address"), "")]

	address = frappe.db.get_value(
		"Address",
		name,
		["address_line1", "address_line2", "city", "state", "pincode", "country"],
		as_dict=True,
	)
	parts = [
		address.address_line1,
		address.address_line2,
		address.city,
		address.state,
		address.pincode,
		address.country,
	]

	return [row(_("Address"), ", ".join(part for part in parts if part))]


# --- the one write this page accepts ------------------------------------------------


def owned_customer(customers: list[str]) -> str:
	"""The customer the request names, checked against the borrower's own list.

	A customer name arrives from the browser, so it is never trusted. This is the same
	rule as assert_owns, applied to the record a write is aimed at rather than a read.
	"""
	name = clean(frappe.form_dict.get("customer"))

	if name not in customers:
		raise frappe.PermissionError(_("Not permitted"))

	return name


def set_primary_row(contact, table: str, value_field: str, value: str, flag: str):
	"""Update the row a Contact child table flags as primary, or add one.

	Contact.email_id and Contact.mobile_no are read-only fields fetched from these
	tables, so writing them directly does nothing. Appending every time would leave a
	borrower with a row per correction, which is why an existing row is reused.

	The match is on the flag alone. `phone_nos` holds the mobile and the landline in
	one table under different flags, so falling back to "the first row" would let a
	landline overwrite the mobile that was saved a moment earlier.
	"""
	if not value:
		return

	rows = contact.get(table) or []
	primary = next((row for row in rows if row.get(flag)), None)

	if primary:
		primary.set(value_field, value)
	else:
		contact.append(table, {value_field: value, flag: 1})


def safe_to_edit(doc, customers: list[str]) -> bool:
	"""True when every customer this record serves is one the borrower owns.

	Frappe creates a Contact per login and erpnext links it to each Customer that
	login is a portal user of, so one record commonly serves several customers. That
	is harmless while they all belong to the same person. It stops being harmless if
	the record also serves a customer somebody else holds: editing it would then
	change what that other borrower sees. In that case a fresh record is made for
	this customer instead of writing to the shared one.
	"""
	served = {row.link_name for row in doc.get("links") or [] if row.link_doctype == "Customer"}

	return served <= set(customers)


def save_contact(customer: str, customers: list[str], data: dict):
	name = primary_contact(frappe.db.get_value("Customer", customer, CUSTOMER_FIELDS, as_dict=True))
	contact = frappe.get_doc("Contact", name) if name else None

	if contact is None or not safe_to_edit(contact, customers):
		contact = frappe.new_doc("Contact")
		contact.first_name = frappe.db.get_value("Customer", customer, "customer_name")
		contact.append("links", {"link_doctype": "Customer", "link_name": customer})

	set_primary_row(contact, "email_ids", "email_id", data["email"], "is_primary")
	set_primary_row(contact, "phone_nos", "phone", data["mobile"], "is_primary_mobile_no")
	set_primary_row(contact, "phone_nos", "phone", data["phone"], "is_primary_phone")

	contact.save(ignore_permissions=True)

	return contact.name


def resolve_country(given: str, existing: str | None) -> str | None:
	"""The country to save, which is never allowed to be blank.

	Address.country is mandatory, and india_compliance refuses an address outside
	India unless its GST category says so. A borrower who leaves the box empty would
	otherwise get that rule quoted at them, which explains nothing. So a blank box
	keeps whatever the address already had, and failing that the site's own country.
	"""
	if given:
		if not frappe.db.exists("Country", given):
			frappe.throw(
				_("We do not recognise {0} as a country.").format(given), frappe.ValidationError
			)
		return given

	return existing or frappe.db.get_single_value("System Settings", "country") or None


def save_address(customer: str, customers: list[str], data: dict):
	name = primary_address(frappe.db.get_value("Customer", customer, CUSTOMER_FIELDS, as_dict=True))
	values = {field: data[field] for field in EDITABLE_ADDRESS}

	if not any(values.values()):
		return None

	address = frappe.get_doc("Address", name) if name else None

	if address is None or not safe_to_edit(address, customers):
		address = frappe.new_doc("Address")
		address.address_type = "Billing"
		address.address_title = frappe.db.get_value("Customer", customer, "customer_name")
		address.append("links", {"link_doctype": "Customer", "link_name": customer})

	values["country"] = resolve_country(values["country"], address.get("country"))
	if not values["country"]:
		frappe.throw(_("Please give a country for your address."), frappe.ValidationError)

	# Address's own mandatory fields, checked here so a borrower who filled in half
	# the form is told what is missing in our words rather than the doctype's.
	# Anything a regional app adds on top -- india_compliance wants a state on an
	# Indian address -- stays that app's rule to state, because it varies by install.
	missing = [field for field in ("address_line1", "city") if not values[field]]
	if missing:
		frappe.throw(
			_("An address needs at least a first line and a city."), frappe.ValidationError
		)

	address.update(values)
	address.save(ignore_permissions=True)

	return address.name


@frappe.whitelist(methods=["POST"])
def save_profile() -> dict:
	"""Correct the contact details and address on one of the borrower's own records.

	Written with ignore_permissions because a Website User holds no write rights on
	Contact or Address, and granting them would open every other borrower's records
	too. The narrowing is done here instead: one customer the borrower owns, and a
	fixed list of fields. Nothing else in the request is read.
	"""
	customers = get_portal_customers()
	customer = owned_customer(customers)

	data = {field: clean(frappe.form_dict.get(field)) for field in EDITABLE_CONTACT}
	data.update({field: clean(frappe.form_dict.get(field)) for field in EDITABLE_ADDRESS})

	if data["email"] and not frappe.utils.validate_email_address(data["email"]):
		frappe.throw(_("Please give a valid email address."), frappe.ValidationError)

	if not data["email"] and not data["mobile"]:
		frappe.throw(
			_("Please leave us at least an email address or a mobile number."),
			frappe.ValidationError,
		)

	save_contact(customer, customers, data)
	save_address(customer, customers, data)

	return {
		"headline": _("Saved"),
		"message": _("Your details have been updated."),
		"offer": [],
		"reference_note": "",
	}
