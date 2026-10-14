// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.listview_settings["Post Disbursal Document"] = {
	get_indicator(doc) {
		const colors = {
			Pending: "orange",
			Overdue: "red",
			Received: "blue",
			Verified: "green",
			Waived: "gray",
		};
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
