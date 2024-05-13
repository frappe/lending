// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

lending.common.setup_filters("Loan Disbursement");

frappe.ui.form.on('Loan Disbursement', {
	setup(frm) {
		frm.ignore_doctypes_on_cancel_all = ["Loan Security Deposit", "Loan Repayment Schedule", "Sales Invoice", "Loan Interest Accrual", "Loan Demand"];
	},
	refresh: function(frm) {
		frm.set_query('against_loan', function() {
			return {
				'filters': {
					'docstatus': 1,
					"status": ["in",["Sanctioned","Active", "Partially Disbursed"]],
				}
			}
		})
	}
});
