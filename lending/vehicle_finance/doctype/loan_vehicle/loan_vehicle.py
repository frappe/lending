# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
REGISTRATION_PATTERN = re.compile(r"^([A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}|\d{2}BH\d{4}[A-Z]{1,2})$")
ACTIVE_STATUSES = ("Proposed", "Financed", "Repossessed")


class LoanVehicle(Document):
	def validate(self):
		self.normalise_identifiers()
		self.set_applicant_name()
		self.set_title()
		self.validate_loan_security_type()
		self.validate_identifiers_for_used_vehicles()
		self.validate_unique_identifiers()
		self.warn_on_identifier_format()
		self.set_asset_value()

	def on_update(self):
		self.sync_loan_security()

	def on_trash(self):
		if self.status != "Proposed":
			frappe.throw(_("Only a Proposed vehicle can be deleted"))

		if self.loan_security:
			loan_security = self.loan_security
			self.db_set("loan_security", None)
			frappe.delete_doc("Loan Security", loan_security, ignore_permissions=True)

	def normalise_identifiers(self):
		for fieldname in ("chassis_number", "engine_number", "registration_number"):
			value = self.get(fieldname)
			if value:
				self.set(fieldname, re.sub(r"[\s-]", "", value).upper())

	def set_applicant_name(self):
		if self.applicant_type == "Customer":
			self.applicant_name = frappe.db.get_value("Customer", self.applicant, "customer_name")
		elif self.applicant_type == "Employee":
			self.applicant_name = frappe.db.get_value("Employee", self.applicant, "employee_name")

	def set_title(self):
		self.title = " ".join(
			filter(None, [self.vehicle_model, self.registration_number or self.chassis_number])
		)

	def validate_loan_security_type(self):
		is_vehicle = frappe.db.get_value("Loan Security Type", self.loan_security_type, "is_vehicle")
		if not is_vehicle:
			frappe.throw(
				_("Loan Security Type {0} is not marked as a vehicle type").format(
					frappe.bold(self.loan_security_type)
				)
			)

	def validate_identifiers_for_used_vehicles(self):
		if self.asset_condition == "New":
			return

		missing = [
			self.meta.get_label(fieldname)
			for fieldname in ("chassis_number", "engine_number", "registration_number", "rc_copy")
			if not self.get(fieldname)
		]
		if missing:
			frappe.throw(
				_("{0} is required for a {1} vehicle").format(", ".join(missing), self.asset_condition)
			)

	def validate_unique_identifiers(self):
		for fieldname in ("chassis_number", "engine_number", "registration_number"):
			value = self.get(fieldname)
			if not value:
				continue

			duplicate = frappe.db.get_value(
				"Loan Vehicle",
				{fieldname: value, "name": ("!=", self.name), "status": ("in", ACTIVE_STATUSES)},
				["name", "status"],
				as_dict=1,
			)
			if duplicate:
				frappe.throw(
					_("{0} {1} is already used on vehicle {2} ({3})").format(
						self.meta.get_label(fieldname),
						frappe.bold(value),
						frappe.bold(duplicate.name),
						duplicate.status,
					),
					title=_("Duplicate Vehicle"),
				)

	def warn_on_identifier_format(self):
		if self.chassis_number and self.manufacturing_year and self.manufacturing_year >= 2010:
			if not VIN_PATTERN.match(self.chassis_number):
				frappe.msgprint(
					_("Chassis number {0} is not a 17 character VIN").format(frappe.bold(self.chassis_number)),
					indicator="orange",
					alert=True,
				)

		if self.registration_number and not REGISTRATION_PATTERN.match(self.registration_number):
			frappe.msgprint(
				_("Registration number {0} does not look like an Indian registration number").format(
					frappe.bold(self.registration_number)
				),
				indicator="orange",
				alert=True,
			)

	def set_asset_value(self):
		if self.status != "Proposed":
			return

		if self.asset_condition == "New":
			self.asset_value = flt(self.invoice_value)
		elif self.valuation:
			self.asset_value = flt(frappe.db.get_value("Vehicle Valuation", self.valuation, "market_value"))
		else:
			self.asset_value = 0

	def sync_loan_security(self):
		values = {
			"loan_security_name": self.title or self.name,
			"loan_security_type": self.loan_security_type,
		}
		if self.status == "Proposed":
			values["original_security_value"] = self.asset_value

		if self.loan_security and frappe.db.exists("Loan Security", self.loan_security):
			loan_security = frappe.get_doc("Loan Security", self.loan_security)
			loan_security.update(values)
			loan_security.save(ignore_permissions=True)
			return

		loan_security = frappe.get_doc(
			{
				"doctype": "Loan Security",
				"loan_security_code": self.name,
				"vehicle": self.name,
				**values,
			}
		)
		loan_security.insert(ignore_permissions=True)
		self.db_set("loan_security", loan_security.name)


def get_vehicle_for_loan_security(loan_security):
	return frappe.db.get_value("Loan Security", loan_security, "vehicle")


@frappe.whitelist()
def cancel_vehicle(vehicle: str):
	doc = frappe.get_doc("Loan Vehicle", vehicle)
	doc.check_permission("write")

	if doc.status != "Proposed":
		frappe.throw(_("Only a Proposed vehicle can be cancelled"))

	doc.db_set("status", "Cancelled")


@frappe.whitelist()
def mark_repossessed(vehicle: str):
	doc = frappe.get_doc("Loan Vehicle", vehicle)
	doc.check_permission("write")

	if doc.status != "Financed":
		frappe.throw(_("Only a Financed vehicle can be marked as repossessed"))

	doc.db_set("status", "Repossessed")

	assignments = frappe.get_all(
		"Pledge",
		filters={"loan_security": doc.loan_security, "parenttype": "Loan Security Assignment"},
		pluck="parent",
	)
	for assignment in frappe.get_all(
		"Loan Security Assignment",
		filters={"name": ("in", assignments), "loan": doc.current_loan, "status": "Pledged", "docstatus": 1},
		pluck="name",
	):
		frappe.db.set_value("Loan Security Assignment", assignment, "status", "Repossessed")


@frappe.whitelist()
def mark_hypothecation_terminated(vehicle: str, termination_date: str | None = None):
	doc = frappe.get_doc("Loan Vehicle", vehicle)
	doc.check_permission("write")

	if doc.status not in ("Released", "Sold"):
		frappe.throw(_("Hypothecation can only be terminated on a Released or Sold vehicle"))

	if doc.hypothecation_status == "Terminated":
		frappe.throw(_("Hypothecation is already terminated"))

	doc.db_set(
		{
			"hypothecation_status": "Terminated",
			"hypothecation_terminated_on": getdate(termination_date or nowdate()),
		}
	)
