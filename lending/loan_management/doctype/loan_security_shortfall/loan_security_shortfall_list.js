// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.listview_settings["Loan Security Shortfall"] = {
	add_fields: ["status", "email_missing", "missing_price"],
	get_indicator(doc) {
		if (doc.status !== "Completed" && doc.email_missing) {
			return [__("Email Missing"), "orange", "email_missing,=,1"];
		}
		if (doc.status !== "Completed" && doc.missing_price) {
			return [__("Prices Missing"), "orange", "missing_price,=,1"];
		}

		const colors = {
			Pending: "orange",
			Notified: "yellow",
			Escalated: "red",
			"Sale Triggered": "red",
			Completed: "green",
		};
		return [__(doc.status), colors[doc.status], "status,=," + doc.status];
	},
};
