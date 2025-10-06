import frappe
from frappe import _


def validate_loan_tables(doc, method=None):
	loan_classification_ranges = set()
	for d in doc.loan_classification_ranges:
		key = (d.classification_code, d.is_written_off)
		if key in loan_classification_ranges:
			frappe.throw(
				_("Classification {0} added multiple times").format(frappe.bold(d.classification_code))
			)
		loan_classification_ranges.add(key)

	irac_provisioning_configurations = set()
	for d in doc.irac_provisioning_configuration:
		key = (d.classification_code, d.security_type)
		if key in irac_provisioning_configurations:
			frappe.throw(
				_("Classification {0} with security type {1} added multiple times").format(
					frappe.bold(d.classification_code), frappe.bold(d.security_type)
				)
			)
		irac_provisioning_configurations.add(key)
