// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Process Loan Interest Change", {
	refresh(frm) {
		frm.set_intro(__("Once submitted, the process cannot be reversed "));
	},
});
