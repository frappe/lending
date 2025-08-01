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
			},
			"get_query": function() {
				let applicant_type = frappe.query_report.get_filter_value('applicant_type');
				let company = frappe.query_report.get_filter_value('company');

				if (applicant_type === "Employee") {
					return {
						filters: {
							company: company
						}
					};
				}
				return {};
			}
		},
		{
			"fieldname":"loan_product",
			"label": __("Loan Product"),
			"fieldtype": "Link",
			"options": "Loan Product",
			get_query: () => {
				var company = frappe.query_report.get_filter_value("company");
				return {
					filters: {
						company: company,
					},
				};
			},
			on_change: function() {
				frappe.query_report.set_filter_value("loan", "");
				frappe.query_report.set_filter_value("loan_disbursement", "");
				frappe.query_report.refresh();
			}
		},
		{
			"fieldname":"loan",
			"label": __("Loan"),
			"fieldtype": "Link",
			"options": "Loan",
			get_query: () => {
				var company = frappe.query_report.get_filter_value("company");
				var loan_product = frappe.query_report.get_filter_value("loan_product");
				return {
					filters: {
						company: company,
						docstatus: 1,
						loan_product: loan_product || undefined,
					},
				};
			},
			on_change: function() {
				frappe.query_report.set_filter_value("loan_disbursement", "");
				frappe.query_report.refresh();
			}
		},
		{
			"fieldname":"loan_disbursement",
			"label": __("Loan Disbursement"),
			"fieldtype": "Link",
			"options": "Loan Disbursement",
			get_query: () => {
				var company = frappe.query_report.get_filter_value("company");
				var loan = frappe.query_report.get_filter_value("loan");
				var loan_product = frappe.query_report.get_filter_value("loan_product");
				return {
					filters: {
						company: company,
						docstatus: 1,
						against_loan: loan || undefined,
						loan_product: loan_product || undefined,
					},
				};
			},
		},
	],
};
