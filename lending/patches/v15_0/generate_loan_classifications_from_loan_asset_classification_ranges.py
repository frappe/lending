# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	classification_ranges = frappe.get_all(
		"Loan Classification Range",
		fields=[
			"classification_code",
			"classification_name",
		],
	)

	for classification_range in classification_ranges:
		loan_classification = frappe.new_doc("Loan Classification")
		loan_classification.classification_code = classification_range.classification_code
		loan_classification.classification_name = classification_range.classification_name
		loan_classification.flags.ignore_validate = True
		loan_classification.insert()
