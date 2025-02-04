// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

lending.common.setup_filters("Loan Disbursement");

frappe.ui.form.on('Loan Disbursement', {
	setup(frm) {
		frm.ignore_doctypes_on_cancel_all = ["Loan Security Deposit", "Loan Repayment Schedule",
			"Sales Invoice", "Loan Interest Accrual", "Loan Demand", "Loan Restructure", "Loan Repayment", "Process Loan Classification"];
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
		if (frm.doc.docstatus == 1 && frm.doc.repayment_schedule_type && frm.doc.status != "Closed") {
			frm.add_custom_button(__('Loan Repayment'), function() {
				frm.trigger("make_repayment_entry");
			},__('Create'));
		}
	},
	make_repayment_entry: function(frm) {
		frappe.call({
			args: {
				"loan": frm.doc.against_loan,
				"applicant_type": frm.doc.applicant_type,
				"applicant": frm.doc.applicant,
				"loan_product": frm.doc.loan_product,
				"company": frm.doc.company,
				"loan_disbursement": frm.doc.name,
				"as_dict": 1
			},
			method: "lending.loan_management.doctype.loan.loan.make_repayment_entry",
			callback: function (r) {
				if (r.message)
					var doc = frappe.model.sync(r.message)[0];
				frappe.set_route("Form", doc.doctype, doc.name);
			}
		})
	},
});
