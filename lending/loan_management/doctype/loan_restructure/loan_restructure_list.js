// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.listview_settings['Loan Restructure'] = {
	get_indicator: function(doc) {
		let status_color = {
			"Draft": "red",
			"Initiated": "blue",
			"Rejected": "red",
			"Approved": "green",
		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	},
};