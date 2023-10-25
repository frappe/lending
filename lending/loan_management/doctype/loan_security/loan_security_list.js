frappe.listview_settings['Loan Security'] = {
	get_indicator: function(doc) {
		var status_color = {
			"Pending Hypothecation": "grey",
			"Hypothecated": "blue",
			"Released": "green",
			"Repossessed": "red"
		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	},
};