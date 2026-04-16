// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Loan Statement of Account"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "applicant_type",
			label: __("Applicant Type"),
			fieldtype: "Select",
			options: ["Customer", "Employee"],
			reqd: 1,
			default: "Customer",
			on_change: function () {
				frappe.query_report.set_filter_value("applicant", "");
				frappe.query_report.set_filter_value("loan", "");
			},
		},
		{
			fieldname: "applicant",
			label: __("Applicant"),
			fieldtype: "Dynamic Link",
			get_options: function () {
				var applicant_type = frappe.query_report.get_filter_value("applicant_type");
				var applicant = frappe.query_report.get_filter_value("applicant");
				if (applicant && !applicant_type) {
					frappe.throw(__("Please select Applicant Type first"));
				}
				return applicant_type;
			},
		},
		{
			fieldname: "loan",
			label: __("Loan"),
			fieldtype: "Link",
			options: "Loan",
			get_query: function () {
				let filters = {
					company: frappe.query_report.get_filter_value("company"),
				};
				let applicant = frappe.query_report.get_filter_value("applicant");
				if (applicant) {
					filters["applicant"] = applicant;
				}
				return { filters: filters };
			},
		},
		{
			fieldname: "loan_product",
			label: __("Loan Product"),
			fieldtype: "Link",
			options: "Loan Product",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "group_by",
			label: __("View"),
			fieldtype: "Select",
			options: ["Detailed", "Grouped"],
			default: "Detailed",
		},
	],
};
