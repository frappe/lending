// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Loan Security Ledger"] = {
	filters: [
		{
			"fieldname": "loan",
			"label": __("Loan"),
			"fieldtype": "Link",
			"options": "Loan",
			"reqd": 1,
		},
		{
			"fieldname": "loan_security",
			"label": __("Loan Security"),
			"fieldtype": "Link",
			"options": "Loan Security",
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname == "qty" && data && row[2].content == "Loan Security Release") {
			value = "<span style='color:red'>" + value + "</span>";
		} else if (column.fieldname == "qty" && data && row[2].content == "Loan Security Assignment") {
			value = "<span style='color:green'>" + value + "</span>";
		}

		return value;
	},
};
