// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Security Shortfall', {
	refresh: function(frm) {
		frm.add_custom_button(__("Add Loan Security"), function() {
			frm.trigger('shortfall_action');
		});

		if (frm.doc.email_missing && frm.doc.status !== "Completed") {
			frm.set_intro(
				__("The borrower has no email address, so no margin call notice was sent and the cure period has not started. Add an email to {0}, and the next daily run sends the notice.", [frm.doc.applicant]),
				"orange"
			);
		}
	},

	shortfall_action: function(frm) {
		frappe.call({
			method: "lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall.add_security",
			args: {
				'loan': frm.doc.loan
			},
			callback: function(r) {
				if (r.message) {
					let doc = frappe.model.sync(r.message)[0];
					frappe.set_route("Form", doc.doctype, doc.name);
				}
			}
		});
	}
});
