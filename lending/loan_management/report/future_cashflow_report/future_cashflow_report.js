// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Future Cashflow Report"] = {
	filters: [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname": "as_on_date",
			"label": __("As on Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1,
		},
		{
			"fieldname": "loan_product",
			"label": __("Loan Product"),
			"fieldtype": "Link",
			"options": "Loan Product",
			get_query: () => {
				let company = frappe.query_report.get_filter_value("company");
				return {
					filters: {
						company: company,
					},
				};
			},
			on_change: function() {
				frappe.query_report.set_filter_value("loan", "");
				frappe.query_report.refresh();
			}
		},
		{
			"fieldname": "loan",
			"label": __("Loan"),
			"fieldtype": "Link",
			"options": "Loan",
			get_query: () => {
				let company = frappe.query_report.get_filter_value("company");
				let loan_product = frappe.query_report.get_filter_value("loan_product");
				return {
					filters: {
						company: company,
						docstatus: 1,
						loan_product: loan_product || undefined,
					},
				};
			},
		},
		{
			"fieldname": "loan_disbursement",
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
