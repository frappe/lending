// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Product", {
	refresh: function(frm) {
		frm.trigger("calculate_interest");
	},

	calculation_model: function(frm) {
		frm.trigger("calculate_interest");
	},

	interest_margin: function(frm) {
		frm.trigger("calculate_interest");
	},

	interest_rate: function(frm) {
		frm.trigger("calculate_interest");
	},

	calculate_interest: function(frm) {
		switch (frm.doc.calculation_model) {
			case "Fixed margin":
				frm.set_value("interest_rate", frm.doc.base_interest_rate + frm.doc.interest_margin);
				break;
			case "Fixed nominal rate":
				frm.set_value("interest_margin", frm.doc.interest_rate - frm.doc.base_interest_rate);
				break;
			case "Advanced":
				break;
		}
	}

 });
