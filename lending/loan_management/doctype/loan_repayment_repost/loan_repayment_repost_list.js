frappe.listview_settings["Loan Repayment Repost"] = {
	has_indicator_for_draft: 1,
	get_indicator: function (doc) {
		const colors = {
			Draft: "red",
			Queued: "yellow",
			"In Process": "orange",
			Completed: "green",
			Cancelled: "red",
		};
		const status = doc.status || "Draft";
		return [__(status), colors[status], "status,=," + status];
	},
};
