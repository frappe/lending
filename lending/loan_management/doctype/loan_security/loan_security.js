// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Security', {
	refresh: function(frm) {
		if (frm.doc.status === "Hypothecated") {
			frm.add_custom_button(__("Release"), function() {
				frm.trigger("release_loan_security");
			})
		}
	},

	release_loan_security: function(frm) {
		frappe.confirm(__("Do you really want to release this loan security?"), function () {
			frappe.call({
				args: {
					"loan_security": frm.doc.name,
				},
				method: "lending.loan_management.doctype.loan_security.loan_security.release_loan_security",
				callback: function(r) {
					cur_frm.reload_doc();
				}
			})
		})
	},
});
