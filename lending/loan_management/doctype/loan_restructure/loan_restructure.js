// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Restructure", {
	refresh: function (frm) {
		frm.trigger("toggle_fields");
		frm.ignore_doctypes_on_cancel_all = ['Loan Balance Adjustment', 'Loan Repayment', 'Loan Repayment Schedule', 'Process Loan Classification'];
	},

	new_repayment_method: function (frm) {
		frm.trigger("toggle_fields");
	},


	loan: function (frm) {
		if (frm.doc.loan && frm.doc.restructure_date) {
			frm.trigger("calculate_overdue_amounts");
		}

		frappe.call({
			"method": "set_completed_tenure",
			"doc": frm.doc,
			callback: function (r) {
				frm.set_value("completed_tenure", r.message);
			}
		});
	},

	restructure_date: function (frm) {
		if (frm.doc.loan && frm.doc.restructure_date) {
			frm.trigger("calculate_overdue_amounts");
		}
	},

	toggle_fields: function (frm) {
		frm.toggle_enable("new_monthly_repayment_amount", frm.doc.new_repayment_method == "Repay Fixed Amount per Period");
		frm.toggle_enable("new_repayment_period_in_months", frm.doc.new_repayment_method == "Repay Over Number of Periods");
	},

	calculate_overdue_amounts: function(frm) {
		frappe.call({
			method: 'lending.loan_management.doctype.loan_repayment.loan_repayment.calculate_amounts',
			args: {
				'against_loan': frm.doc.loan,
				'posting_date': frm.doc.restructure_date,
				'payment_type': ''
			},
			callback: function(r) {
				let amounts = r.message;
				frm.set_value("pending_principal_amount", amounts["pending_principal_amount"]);
				frm.set_value("total_overdue_amount", amounts["payable_amount"]);
				frm.set_value("principal_overdue", amounts["payable_principal_amount"]);
				frm.set_value("interest_overdue", amounts["interest_amount"]);
				frm.set_value("penalty_overdue", amounts["penalty_amount"]);
				frm.set_value("charges_overdue", amounts["total_charges_payable"]);
				frm.set_value("unaccrued_interest", amounts["unaccrued_interest"]);
				frm.set_value("available_security_deposit", amounts["available_security_deposit"]);
			}
		});
	}
});