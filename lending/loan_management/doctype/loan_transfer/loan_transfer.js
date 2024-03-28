// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Transfer", {
	setup(frm) {
		frm.ignore_doctypes_on_cancel_all = ["Journal Entry"]
	},
});
