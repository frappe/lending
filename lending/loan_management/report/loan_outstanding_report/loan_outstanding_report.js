// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Loan Outstanding Report"] = {
	filters: [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname":"applicant_type",
			"label": __("Applicant Type"),
			"fieldtype": "Select",
			"options": ["Customer", "Employee"],
			"reqd": 1,
			"default": "Customer",
			on_change: function() {
				frappe.query_report.set_filter_value('applicant', "");
			}
		},
		{
			"fieldname": "applicant",
			"label": __("Applicant"),
			"fieldtype": "Dynamic Link",
			"get_options": function() {
				var applicant_type = frappe.query_report.get_filter_value('applicant_type');
				var applicant = frappe.query_report.get_filter_value('applicant');
				if(applicant && !applicant_type) {
					frappe.throw(__("Please select Applicant Type first"));
				}
				return applicant_type;
			},
		},
		{
			"fieldname":"loan_product",
			"label": __("Loan Product"),
			"fieldtype": "Link",
			"options": "Loan Product",
		},
		{
			"fieldname":"loan",
			"label": __("Loan"),
			"fieldtype": "Link",
			"options": "Loan",
		},
		{
			"fieldname":"loan_disbursement",
			"label": __("Loan Disbursement"),
			"fieldtype": "Link",
			"options": "Loan Disbursement",
		},
	],
};
