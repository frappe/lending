// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

lending.common.setup_filters("Loan Repayment");

frappe.ui.form.on('Loan Repayment', {
	setup(frm) {
		frm.ignore_doctypes_on_cancel_all = ["Process Loan Classification"];
		if (frappe.meta.has_field("Loan Repayment", "repay_from_salary")) {
			frm.add_fetch("against_loan", "repay_from_salary", "repay_from_salary");
		}
	},

	onload: function(frm) {
		frm.set_query('against_loan', function() {
			return {
				'filters': {
					'docstatus': 1
				}
			};
		});

		if (frm.doc.against_loan && frm.doc.posting_date && frm.doc.docstatus == 0) {
			frm.trigger('calculate_repayment_amounts');
		}
	},

	posting_date : function(frm) {
		frm.trigger('calculate_repayment_amounts');
	},

	against_loan: function(frm) {
		if (frm.doc.posting_date) {
			frm.trigger('calculate_repayment_amounts');
		}
	},

	payment_type: function(frm) {
		if (frm.doc.posting_date) {
			frm.trigger('calculate_repayment_amounts');
		}
	},

	calculate_repayment_amounts: function(frm) {
		frappe.call({
			method: 'lending.loan_management.doctype.loan_repayment.loan_repayment.calculate_amounts',
			args: {
				'against_loan': frm.doc.against_loan,
				'posting_date': frm.doc.posting_date,
				'payment_type': frm.doc.payment_type
			},
			callback: function(r) {
				let amounts = r.message;
				frm.set_value('amount_paid', 0.0);
				frm.set_df_property('amount_paid', 'read_only', frm.doc.payment_type == "Loan Closure" ? 1:0);

				frm.set_value('pending_principal_amount', amounts['pending_principal_amount']);
				if (frm.doc.is_term_loan || frm.doc.payment_type == "Loan Closure") {
					frm.set_value('payable_principal_amount', amounts['payable_principal_amount']);
					frm.set_value('amount_paid', amounts['payable_amount']);
				}
				frm.set_value('interest_payable', amounts['interest_amount']);
				frm.set_value('penalty_amount', amounts['penalty_amount']);
				frm.set_value('payable_amount', amounts['payable_amount']);
				frm.set_value('total_charges_payable', amounts['total_charges_payable']);

				if (amounts["charges"]) {
					frm.clear_table("pending_charges");
					amounts["charges"].forEach(d => {
						let row = frm.add_child('pending_charges');
						row.sales_invoice = d.sales_invoice;
						row.pending_charge_amount = d.pending_charge_amount;
					})
					frm.refresh_field('pending_charges');
				}

			}
		});
	}
});