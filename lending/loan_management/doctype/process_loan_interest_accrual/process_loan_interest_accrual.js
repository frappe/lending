// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Process Loan Interest Accrual', {
	refresh: function(frm) {
		frm.set_query("loan_type", function() {
			return {
				filters: {
					"docstatus": 1
				}
			};
		});
	}
});
