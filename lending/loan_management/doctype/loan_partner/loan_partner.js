// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Partner", {
    setup: function(frm) {
		frm.set_query('primary_address', function(doc) {
			return {
				filters: {
					'link_doctype': 'Loan Partner',
					'link_name': doc.name
				}
			}
		})
	},

	refresh: function(frm) {
		if(!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);
	    } else {
			frappe.contacts.clear_address_and_contact(frm);
        }
    },
});
