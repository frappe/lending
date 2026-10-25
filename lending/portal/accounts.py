# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

CUSTOMER_TYPES = {"Individual": "Individual", "Business": "Company"}


def customer_for_email(email: str) -> str | None:
	if not email:
		return None

	# Customer.email_id is fetched from the primary contact and often empty, so match via Contact.
	linked = frappe.get_all(
		"Contact",
		filters=[
			["Contact Email", "email_id", "=", email],
			["Dynamic Link", "link_doctype", "=", "Customer"],
		],
		fields=["`tabDynamic Link`.link_name as customer"],
		limit=1,
	)
	if linked:
		return linked[0].customer

	return frappe.db.get_value("Customer", {"email_id": email}, "name")


def create_customer(customer_name: str, customer_type: str, email: str, mobile: str) -> str:
	"""Creates a primary Contact too, else customer_for_email cannot find it later."""
	customer = frappe.new_doc("Customer")
	customer.update({"customer_name": customer_name, "customer_type": customer_type})
	customer.insert(ignore_permissions=True)

	contact = frappe.new_doc("Contact")
	contact.first_name = customer_name
	if email:
		contact.append("email_ids", {"email_id": email, "is_primary": 1})
	if mobile:
		contact.append("phone_nos", {"phone": mobile, "is_primary_mobile_no": 1})
	contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})
	contact.insert(ignore_permissions=True)

	customer.customer_primary_contact = contact.name
	customer.save(ignore_permissions=True)

	return customer.name


def customer_for_applicant(
	customer_name: str, applicant_type: str, email: str, mobile: str
) -> str:
	"""The Customer a self-signup joins; anything short of clear ownership gets a new one."""
	return customer_owning_email(email) or create_customer(
		customer_name, CUSTOMER_TYPES.get(applicant_type, "Individual"), email, mobile
	)


def customer_owning_email(email: str) -> str | None:
	"""The one unclaimed Customer whose primary address this is.

	Not customer_for_email: joining grants the Customer's loans, and any of its Contacts, such
	as a clerk or a shared inbox, could verify an address that matches there.
	"""
	if not email:
		return None

	contacts = frappe.get_all(
		"Contact Email",
		filters={"email_id": email, "is_primary": 1, "parenttype": "Contact"},
		pluck="parent",
	)
	owners = set(frappe.get_all("Customer", filters={"email_id": email}, pluck="name"))
	if contacts:
		owners.update(
			frappe.get_all("Customer", filters={"customer_primary_contact": ["in", contacts]}, pluck="name")
		)

	if len(owners) != 1:
		return None

	customer = owners.pop()
	# A Customer someone already logs in to is theirs; a second login is staff's to grant.
	if frappe.db.exists("Portal User", {"parenttype": "Customer", "parent": customer}):
		return None

	return customer


def link_portal_user(customer: str, user: str) -> bool:
	"""Returns whether a row was added; a no-op when the User does not exist yet."""
	if not customer or not user or not frappe.db.exists("User", user):
		return False

	record = frappe.get_doc("Customer", customer)
	if any(row.user == user for row in record.portal_users):
		return False

	record.append("portal_users", {"user": user})
	record.save(ignore_permissions=True)

	return True
