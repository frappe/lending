# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.contacts.address_and_contact import load_address_and_contact

# import frappe
from frappe.model.document import Document


class LoanPartner(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)
