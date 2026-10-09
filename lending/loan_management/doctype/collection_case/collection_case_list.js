// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.listview_settings['Collection Case'] = {
	get_indicator: function(doc) {
		let status_color = {
			"Open": "orange",
			"In Progress": "blue",
			"Promise to Pay": "yellow",
			"Broken PTP": "red",
			"Hardship Requested": "purple",
			"Resolved": "green",
			"Closed": "grey",
		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	},
};
