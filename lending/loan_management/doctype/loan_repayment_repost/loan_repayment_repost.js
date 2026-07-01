// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Repayment Repost", {
	refresh(frm) {
		if (["Queued", "In Process"].includes(frm.doc.status)) {
			frm.disable_save();
			frm.page.clear_primary_action();
			frm.set_read_only();
			frm.dashboard.clear_comment();
			frm.dashboard.add_comment(
				__("This repost is {0} in the background. Please wait for it to finish.", [
					__(frm.doc.status),
				]),
				"blue",
				true
			);
		}
	},
});
