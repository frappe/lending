// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["PDD Ageing"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "as_on_date", label: __("As On Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "loan", label: __("Loan"), fieldtype: "Link", options: "Loan" },
		{ fieldname: "document_type", label: __("Document Type"), fieldtype: "Link", options: "Loan Document Type" },
	],
};
