// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Pledged Collateral"] = {
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
			fieldname: "loan",
			label: __("Loan"),
			fieldtype: "Link",
			options: "Loan",
		},
		{
			fieldname: "applicant",
			label: __("Applicant"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "loan_security_type",
			label: __("Loan Security Type"),
			fieldtype: "Link",
			options: "Loan Security Type",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// A security with no current price counts at 0 in the shortfall check
		if (column.fieldname === "price" && data && !data.price) {
			value = `<span style="color: var(--red-600)">${__("No current price")}</span>`;
		}
		return value;
	},
};
