# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class VehicleValuation(Document):
	def validate(self):
		self.validate_vehicle_status()

	def on_submit(self):
		self.update_vehicle()

	def on_cancel(self):
		self.validate_vehicle_status()
		self.update_vehicle()

	def validate_vehicle_status(self):
		status = frappe.db.get_value("Loan Vehicle", self.vehicle, "status")
		if status != "Proposed":
			frappe.throw(
				_("Vehicle {0} is {1}. Its value is frozen once it is financed.").format(
					frappe.bold(self.vehicle), status
				)
			)

	def update_vehicle(self):
		latest = frappe.get_all(
			"Vehicle Valuation",
			filters={"vehicle": self.vehicle, "docstatus": 1},
			order_by="valuation_date desc, creation desc",
			pluck="name",
			limit=1,
		)
		vehicle = frappe.get_doc("Loan Vehicle", self.vehicle)
		vehicle.valuation = latest[0] if latest else None
		vehicle.save(ignore_permissions=True)
