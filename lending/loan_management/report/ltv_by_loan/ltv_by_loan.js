// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["LTV by Loan"] = {
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
			fieldname: "applicant",
			label: __("Applicant"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "loan_product",
			label: __("Loan Product"),
			fieldtype: "Link",
			options: "Loan Product",
		},
		{
			fieldname: "only_above_ltv",
			label: __("Only Loans Above LTV"),
			fieldtype: "Check",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "headroom" && data && data.headroom < 0) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
