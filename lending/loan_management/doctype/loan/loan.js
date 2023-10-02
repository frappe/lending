// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

lending.common.setup_filters("Loan");

frappe.ui.form.on('Loan', {
	setup: function(frm) {
		frm.make_methods = {
			'Loan Disbursement': function() { frm.trigger('make_loan_disbursement') },
			'Loan Security Unpledge': function() { frm.trigger('create_loan_security_unpledge') },
			'Loan Write Off': function() { frm.trigger('make_loan_write_off_entry') }
		}
	},
	onload: function (frm) {
		// Ignore loan security pledge on cancel of loan
		frm.ignore_doctypes_on_cancel_all = ["Loan Security Pledge", "Loan Repayment Schedule"];

		frm.set_query("loan_application", function () {
			return {
				"filters": {
					"applicant": frm.doc.applicant,
					"docstatus": 1,
					"status": "Approved"
				}
			};
		});

		frm.set_query("loan_product", function () {
			return {
				"filters": {
					"company": frm.doc.company
				}
			};
		});

		$.each(["penalty_income_account", "interest_income_account"], function(i, field) {
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
		})

	},

	refresh: function (frm) {
		if (frm.doc.repayment_schedule_type == "Pro-rated calendar months") {
			frm.set_df_property("repayment_start_date", "label", "Interest Calculation Start Date");
		}

		if (frm.doc.docstatus == 1) {
			if (["Disbursed", "Partially Disbursed"].includes(frm.doc.status) && (!frm.doc.repay_from_salary)) {
				frm.add_custom_button(__('Request Loan Closure'), function() {
					frm.trigger("request_loan_closure");
				},__('Status'));

				frm.add_custom_button(__('Loan Repayment'), function() {
					frm.trigger("make_repayment_entry");
				},__('Create'));
			}

			if (["Sanctioned", "Partially Disbursed"].includes(frm.doc.status)) {
				frm.add_custom_button(__('Loan Disbursement'), function() {
					frm.trigger("make_loan_disbursement");
				},__('Create'));
			}

			if (frm.doc.status == "Loan Closure Requested") {
				frm.add_custom_button(__('Loan Security Unpledge'), function() {
					frm.trigger("create_loan_security_unpledge");
				},__('Create'));
			}

			if (["Loan Closure Requested", "Disbursed", "Partially Disbursed"].includes(frm.doc.status)) {
				frm.add_custom_button(__('Loan Write Off'), function() {
					frm.trigger("make_loan_write_off_entry");
				},__('Create'));

				frm.add_custom_button(__('Loan Refund'), function() {
					frm.trigger("make_loan_refund");
				},__('Create'));
			}

			if (frm.doc.status == "Loan Closure Requested" && frm.doc.is_term_loan && !frm.doc.is_secured_loan) {
				frm.add_custom_button(__('Close Loan'), function() {
					frm.trigger("close_unsecured_term_loan");
				},__('Status'));
			}
		}
		frm.trigger("toggle_fields");
	},

	repayment_schedule_type: function(frm) {
		if (frm.doc.repayment_schedule_type == "Pro-rated calendar months") {
			frm.set_df_property("repayment_start_date", "label", "Interest Calculation Start Date");
		} else {
			frm.set_df_property("repayment_start_date", "label", "Repayment Start Date");
		}
	},

	loan_product: function(frm) {
		frm.toggle_reqd("repayment_method", frm.doc.is_term_loan);
		frm.toggle_display("repayment_method", frm.doc.is_term_loan);
		frm.toggle_display("repayment_periods", frm.doc.is_term_loan);
	},


	make_loan_disbursement: function (frm) {
		frappe.call({
			args: {
				"loan": frm.doc.name,
				"company": frm.doc.company,
				"applicant_type": frm.doc.applicant_type,
				"applicant": frm.doc.applicant,
				"pending_amount": frm.doc.loan_amount - frm.doc.disbursed_amount > 0 ?
					frm.doc.loan_amount - frm.doc.disbursed_amount : 0,
				"as_dict": 1
			},
			method: "lending.loan_management.doctype.loan.loan.make_loan_disbursement",
			callback: function (r) {
				if (r.message)
					var doc = frappe.model.sync(r.message)[0];
				frappe.set_route("Form", doc.doctype, doc.name);
			}
		})
	},

	make_repayment_entry: function(frm) {
		frappe.call({
			args: {
				"loan": frm.doc.name,
				"applicant_type": frm.doc.applicant_type,
				"applicant": frm.doc.applicant,
				"loan_product": frm.doc.loan_product,
				"company": frm.doc.company,
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

	make_loan_write_off_entry: function(frm) {
		frappe.call({
			args: {
				"loan": frm.doc.name,
				"company": frm.doc.company,
				"as_dict": 1
			},
			method: "lending.loan_management.doctype.loan.loan.make_loan_write_off",
			callback: function (r) {
				if (r.message)
					var doc = frappe.model.sync(r.message)[0];
				frappe.set_route("Form", doc.doctype, doc.name);
			}
		})
	},

	make_loan_refund: function(frm) {
		frappe.call({
			args: {
				"loan": frm.doc.name
			},
			method: "lending.loan_management.doctype.loan.loan.make_refund_jv",
			callback: function (r) {
				if (r.message) {
					let doc = frappe.model.sync(r.message)[0];
					frappe.set_route("Form", doc.doctype, doc.name);
				}
			}
		})
	},

	close_unsecured_term_loan: function(frm) {
		frappe.call({
			args: {
				"loan": frm.doc.name
			},
			method: "lending.loan_management.doctype.loan.loan.close_unsecured_term_loan",
			callback: function () {
				frm.refresh();
			}
		})
	},

	request_loan_closure: function(frm) {
		frappe.confirm(__("Do you really want to close this loan"),
			function() {
				frappe.call({
					args: {
						'loan': frm.doc.name
					},
					method: "lending.loan_management.doctype.loan.loan.request_loan_closure",
					callback: function() {
						frm.reload_doc();
					}
				});
			}
		);
	},

	create_loan_security_unpledge: function(frm) {
		frappe.call({
			method: "lending.loan_management.doctype.loan.loan.unpledge_security",
			args : {
				"loan": frm.doc.name,
				"as_dict": 1
			},
			callback: function(r) {
				if (r.message)
					var doc = frappe.model.sync(r.message)[0];
				frappe.set_route("Form", doc.doctype, doc.name);
			}
		})
	},

	loan_application: function (frm) {
		if(frm.doc.loan_application){
			return frappe.call({
				method: "lending.loan_management.doctype.loan.loan.get_loan_application",
				args: {
					"loan_application": frm.doc.loan_application
				},
				callback: function (r) {
					if (!r.exc && r.message) {

						let loan_fields = ["loan_product", "loan_amount", "repayment_method",
							"monthly_repayment_amount", "repayment_periods", "rate_of_interest", "is_secured_loan"]

						loan_fields.forEach(field => {
							frm.set_value(field, r.message[field]);
						});

						if (frm.doc.is_secured_loan) {
							$.each(r.message.proposed_pledges, function(i, d) {
								let row = frm.add_child("securities");
								row.loan_security = d.loan_security;
								row.qty = d.qty;
								row.loan_security_price = d.loan_security_price;
								row.amount = d.amount;
								row.haircut = d.haircut;
							});

							frm.refresh_fields("securities");
						}
					}
				}
			});
		}
	},

	repayment_method: function (frm) {
		frm.trigger("toggle_fields")
	},

	toggle_fields: function (frm) {
		frm.toggle_enable("monthly_repayment_amount", frm.doc.repayment_method == "Repay Fixed Amount per Period")
		frm.toggle_enable("repayment_periods", frm.doc.repayment_method == "Repay Over Number of Periods")
	}
});