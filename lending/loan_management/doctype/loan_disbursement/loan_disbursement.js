// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

{% include 'lending/loan_management/loan_common.js' %};

frappe.ui.form.on('Loan Disbursement', {
	setup(frm) {
		frm.ignore_doctypes_on_cancel_all = ["Loan Security Deposit"];
	},
	refresh: function(frm) {
		frm.set_query('against_loan', function() {
			return {
				'filters': {
					'docstatus': 1,
					'status': 'Sanctioned'
				}
			}
		})
	}
});
