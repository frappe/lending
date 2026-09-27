# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

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

# Only these fields are read from the request; name and tax_id are KYC-verified and read-only.
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
	asked = frappe.form_dict.get("customer")

	return asked if asked in customers else (customers[0] if customers else None)


def edit_form(customers: list[str]) -> dict:
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
		row(_("Tax id"), customer.tax_id),
	]


def primary_contact(customer: dict) -> str | None:
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


def owned_customer(customers: list[str]) -> str:
	name = clean(frappe.form_dict.get("customer"))

	if name not in customers:
		raise frappe.PermissionError(_("Not permitted"))

	return name


def set_primary_row(contact, table: str, value_field: str, value: str, flag: str):
	# Match on the flag alone: phone_nos holds mobile and landline under different flags.
	if not value:
		return

	rows = contact.get(table) or []
	primary = next((row for row in rows if row.get(flag)), None)

	if primary:
		primary.set(value_field, value)
	else:
		contact.append(table, {value_field: value, flag: 1})


def safe_to_edit(doc, customers: list[str]) -> bool:
	# A Contact/Address shared with another borrower's customer must not be edited in place.
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
	# Never blank: a blank country trips india_compliance's GST-category error.
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
	# ignore_permissions below: Website Users have no Contact/Address rights; scope is enforced here.
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
