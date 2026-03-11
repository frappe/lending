// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Security Release', {
	refresh: function (frm) {
		if (frm.doc.loan) {
			frm.trigger("make_dashboard");
		}
	},
	loan: function (frm) {
		if (frm.doc.loan) {
			frm.trigger("make_dashboard");
		}
	},
	make_dashboard: function (frm) {
		frappe.call({
			method: "lending.loan_management.doctype.loan_security_release.loan_security_release.get_pledged_security_qty",
			args: {
				loan: frm.doc.loan,
			},
			callback: function (r) {
				if (r.message) {
					let pledged_security_summary = r.message;
					if (!$.isEmptyObject(pledged_security_summary)) {
						frm.dashboard.add_section(
							frappe.render_template("pledged_security_summary", {
								data: pledged_security_summary,
							}),
							__("Pledged Security Summary")
						);
						frm.dashboard.show();
					}
				}
			}
		});
	}
});
