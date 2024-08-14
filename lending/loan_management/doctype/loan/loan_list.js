frappe.listview_settings['Loan'] = {
	get_indicator: function(doc) {
		var status_color = {
			"Draft": "red",
			"Sanctioned": "blue",
			"Disbursed": "orange",
			"Partially Disbursed": "yellow",
			"Loan Closure Requested": "green",
			"Closed": "green"
		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	},
	repay_from_salary: function(doc) {
		return doc.repay_from_salary ? [__("Repay From Salary"), "green", "repay_from_salary,=,1"] : null;
	}
};
