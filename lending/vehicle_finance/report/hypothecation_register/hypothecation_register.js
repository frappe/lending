// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Hypothecation Register"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "hypothecation_status", label: __("Hypothecation Status"), fieldtype: "Select", options: "\nNot Endorsed\nEndorsed\nTermination Requested" },
	],
};
