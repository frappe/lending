// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Collateral', {
	refresh: function(frm) {
		if (frm.doc.status === "Hypothecated") {
			frm.add_custom_button(__("Release"), function() {
				frm.trigger("release_loan_collateral");
			})
		}
	},

	release_loan_collateral: function(frm) {
		frappe.confirm(__("Do you really want to release this loan collateral?"), function () {
			frappe.call({
				args: {
					"loan_collateral": frm.doc.name,
				},
				method: "lending.loan_management.doctype.loan_collateral.loan_collateral.release_loan_collateral",
				callback: function(r) {
					cur_frm.reload_doc();
				}
			})
		})
	},
});