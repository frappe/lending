# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class VehicleModel(Document):
	def autoname(self):
		self.name = " ".join(filter(None, [self.make, self.model_name, self.variant]))
