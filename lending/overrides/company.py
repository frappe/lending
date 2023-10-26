import frappe
from frappe import _


def validate_loan_tables(doc, method=None):
	loan_classification_ranges = []
	for d in doc.loan_classification_ranges:
		if d.classification_code not in loan_classification_ranges:
			loan_classification_ranges.append(d.classification_code)
		else:
			frappe.throw(
				_("Classification {0} added multiple times").format(frappe.bold(d.classification_code))
			)

	irac_provisioning_configurations = []
	for d in doc.irac_provisioning_configuration:
		if (d.classification_code, d.security_type) not in irac_provisioning_configurations:
			irac_provisioning_configurations.append((d.classification_code, d.security_type))
		else:
			frappe.throw(
				_("Classification {0} with security type {1} added multiple times").format(
					frappe.bold(d.classification_code), frappe.bold(d.security_type)
				)
			)
