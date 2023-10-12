// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Product', {
	setup(frm) {
		frm.add_fetch("company", "min_days_bw_disbursement_first_repayment", "min_days_bw_disbursement_first_repayment");
	},

	onload: function(frm) {
		$.each(["penalty_income_account", "interest_income_account"], function (i, field) {
			frm.set_query(field, function () {
				return {
					"filters": {
						"company": frm.doc.company,
						"root_type": "Income",
						"is_group": 0
					}
				};
			});
		});

		$.each(["payment_account", "loan_account", "disbursement_account"], function (i, field) {
			frm.set_query(field, function () {
				return {
					"filters": {
						"company": frm.doc.company,
						"root_type": "Asset",
						"is_group": 0
					}
				};
			});
		});
	}
});

frappe.ui.form.on('Loan Charges', {
	charge_type: function(frm, cdt, cdn) {
		const row = locals[cdt][cdn];

		if (!row.charge_type)
			return;

		frappe.call({
			method: "lending.loan_management.doctype.loan_product.loan_product.get_default_charge_accounts",
			args: {
				charge_type: row.charge_type,
				company: frm.doc.company,
			},
			callback: function(r) {
				if(r.message) {
					for (const account_field in r.message) {
						frappe.model.set_value(row.doctype, row.name, account_field, r.message[account_field]);
					}
				}
			}
		});
	},
});
