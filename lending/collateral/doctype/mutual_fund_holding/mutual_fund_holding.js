// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mutual Fund Holding", {
	setup(frm) {
		frm.set_query("loan_security", () => ({ filters: { is_mutual_fund: 1 } }));
	},
});
