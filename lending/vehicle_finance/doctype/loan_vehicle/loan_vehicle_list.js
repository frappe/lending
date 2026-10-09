// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.listview_settings["Loan Vehicle"] = {
	get_indicator(doc) {
		const colors = {
			Proposed: "orange",
			Financed: "blue",
			Repossessed: "red",
			Released: "green",
			Sold: "gray",
			Cancelled: "gray",
		};
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
