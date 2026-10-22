// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.listview_settings["Gold Article"] = {
	get_indicator(doc) {
		const colors = {
			Available: "blue",
			Pledged: "orange",
			Released: "green",
			Sold: "gray",
		};
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
