// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

lending.common.setup_filters("Loan Refund");

frappe.ui.form.on('Loan Refund', {
	refresh: function(frm) {
		frm.set_query("refund_account", function() {
			return {
				filters: {
					"company": frm.doc.company,
					"is_group": 0,
					"disabled": 0
				}
			};
		});
	}
});
