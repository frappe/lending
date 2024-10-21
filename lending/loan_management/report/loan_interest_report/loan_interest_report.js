// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Loan Interest Report"] = {
	"filters": [
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
				frappe.query_report.refresh();
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
			}
		},
		{
			"fieldname":"as_on_date",
			"label": __("As On Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1,
		},
		{
			"fieldname":"name",
			"label": __("Loan"),
			"fieldtype": "Link",
			"options": "Loan",
		},
		{
			"fieldname":"loan_product",
			"label": __("Loan Product"),
			"fieldtype": "Link",
			"options": "Loan Product",
		},
	]
};
