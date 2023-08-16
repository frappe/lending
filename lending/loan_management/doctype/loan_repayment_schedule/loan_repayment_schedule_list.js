// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.listview_settings['Loan Repayment Schedule'] = {
	get_indicator: function(doc) {
		let status_color = {
			"Draft": "red",
			"Active": "green",
			"Restructured": "orange",
		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	},
};
