// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Security Price Update", {
	setup(frm) {
		frm.set_query("loan_security", "items", () => ({
			filters: { loan_security_type: frm.doc.loan_security_type, disabled: 0 },
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.loan_security_type) {
			frm.add_custom_button(__("Get Securities"), () => frm.call("get_securities"));
		}
	},

	loan_security_type(frm) {
		frm.refresh();
	},
});
