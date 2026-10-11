// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Security Type', {
	haircut: function(frm) {
		frm.set_value('loan_to_value_ratio', 100 - flt(frm.doc.haircut));
	},
});
