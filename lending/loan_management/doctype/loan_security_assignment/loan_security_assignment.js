// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Security Assignment', {
	onload: function(frm) {
		frm.set_query("loan_security", "securities", function() {
			return {
				"filters": {
					"status": "Pending Hypothecation",
				}
			};
		});
	},

	refresh: function(frm) {
		if (frm.doc.status === "Release Requested") {
			frm.add_custom_button(__("Release"), function() {
				frm.trigger("release_loan_security_assignment");
			})
		}
	},

	calculate_amounts: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, 'amount', row.qty * row.loan_security_price);
		frappe.model.set_value(cdt, cdn, 'post_haircut_amount', cint(row.amount - (row.amount * row.haircut/100)));

		let amount = 0;
		let maximum_amount = 0;
		$.each(frm.doc.securities || [], function(i, item){
			amount += item.amount;
			maximum_amount += item.post_haircut_amount;
		});

		frm.set_value('total_security_value', amount);
		frm.set_value('maximum_loan_value', maximum_amount);
	},

	release_loan_security_assignment: function(frm) {
		frappe.confirm(__("Do you really want to release this loan security assignment?"), function () {
			frappe.call({
				args: {
					"loan_security_assignment": frm.doc.name,
				},
				method: "lending.loan_management.doctype.loan_security_assignment.loan_security_assignment.release_loan_security_assignment",
				callback: function(r) {
					cur_frm.reload_doc();
				}
			})
		})
	},
});

frappe.ui.form.on("Pledge", {
	loan_security: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];

		if (row.loan_security) {
			frappe.call({
				method: "lending.loan_management.doctype.loan_security_price.loan_security_price.get_loan_security_price",
				args: {
					loan_security: row.loan_security
				},
				callback: function(r) {
					frappe.model.set_value(cdt, cdn, 'loan_security_price', r.message);
					frm.events.calculate_amounts(frm, cdt, cdn);
				}
			});
		}
	},

	qty: function(frm, cdt, cdn) {
		frm.events.calculate_amounts(frm, cdt, cdn);
	},

	loan_security_price: function(frm, cdt, cdn) {
		frm.events.calculate_amounts(frm, cdt, cdn);
	},
});
