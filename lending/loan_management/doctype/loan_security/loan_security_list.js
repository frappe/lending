// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.listview_settings['Loan Security'] = {
	get_indicator: function(doc) {
		var status_color = {
			"Pending Hypothecation": "grey",
			"Hypothecated": "green",
			"Released": "orange",
			"Repossessed": "red"
		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	},
};
