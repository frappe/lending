// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Vehicle Portfolio"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: "Make\nVehicle Model\nSegment\nAsset Condition\nManufacturing Year", default: "Make" },
	],
};
