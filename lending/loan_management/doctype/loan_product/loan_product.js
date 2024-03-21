// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Product', {
	setup(frm) {
		frm.add_fetch("company", "min_days_bw_disbursement_first_repayment", "min_days_bw_disbursement_first_repayment");
	},

	onload: function(frm) {
		const fieldMap = {
			"disbursement_account": "Asset",
			"loan_account": "Asset",
			"payment_account": "Asset",
			"suspense_interest_receivable": "Asset",
			"interest_receivable_account": "Asset",
			"penalty_receivable_account": "Asset",
			"charges_receivable_account": "Asset",
			"security_deposit_account": "Liability",
			"interest_income_account": "Income",
			"penalty_income_account": "Income",
			"suspense_interest_income": "Income",
			"principal_waiver_account": "Expense",
			"interest_waiver_account": "Expense",
			"penalty_waiver_account": "Expense",
			"charges_waiver_account": "Expense",
			"suspense_collection_account": ""
		}

		const createFilters = (company, rootType) => {
			const filters = { "company": company };
			if (rootType) {
				filters["root_type"] = rootType;
			}
			filters["is_group"] = 0;
			return { "filters": filters };
		};

		Object.keys(fieldMap).forEach(field => {
			frm.set_query(field, () => createFilters(frm.doc.company, fieldMap[field]));
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
