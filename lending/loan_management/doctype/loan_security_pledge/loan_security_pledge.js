// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Security Pledge', {
	loan: function(frm, cdt, cdn) {
		frappe.db.get_value("Loan", frm.doc.loan, "collateral_type", (r) => {
			frm.set_value('collateral_type', r.collateral_type);
		});
	},

	loan_application: function(frm, cdt, cdn) {
		frappe.db.get_value("Loan Application", frm.doc.loan_application, "collateral_type", (r) => {
			frm.set_value('collateral_type', r.collateral_type);
		});
	},

	calculate_loan_securities_amounts: function(frm, cdt, cdn) {
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

	calculate_loan_collaterals_amounts: function(frm, cdt, cdn) {
		let amount = 0;
		$.each(frm.doc.collaterals || [], function(i, item){
			amount += item.available_collateral_value;
		});

		frm.set_value('total_security_value', amount);
		frm.set_value('maximum_loan_value', amount);
	}
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
					frm.events.calculate_loan_securities_amounts(frm, cdt, cdn);
				}
			});
		}
	},

	qty: function(frm, cdt, cdn) {
		frm.events.calculate_loan_securities_amounts(frm, cdt, cdn);
	},
});

frappe.ui.form.on("Loan Collateral Assignment Loan Collateral", {
	loan_collateral: function(frm, cdt, cdn) {
		frm.events.calculate_loan_collaterals_amounts(frm, cdt, cdn);
	},
});
