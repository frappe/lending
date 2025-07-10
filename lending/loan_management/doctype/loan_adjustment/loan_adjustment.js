// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

let active_loan_filters = {
	"docstatus": 1,
	"status": ["not in", ["Closed", "Draft"]],
}

const set_loan_filters = (frm, filters) => {
	frm.set_query("loan", function () {
		return {
			"filters": filters,
		};
	});
}

const set_loan_disbursement_filters = (frm, filters) => {
	frm.set_query("loan_disbursement", function () {
		return {
			"filters": filters,
		};
	});
}

frappe.ui.form.on("Loan Adjustment", {
	onload: function (frm) {
		set_loan_filters(frm, active_loan_filters)

		frm.set_query("payment_account", function () {
			return {
				'filters': {
					'is_group': 0,
					'disabled': 0
				}
			};
		});
	},
	loan: function (frm) {
		if (frm.doc.loan) {
			set_loan_disbursement_filters(frm, {"against_loan": frm.doc.loan})
		}
		else {
			set_loan_disbursement_filters(frm, {})
		}
	},
});