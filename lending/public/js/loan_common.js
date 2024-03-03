// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
frappe.provide("lending.common");

lending.common = {
	setup_filters: function(doctype) {
		frappe.ui.form.on(doctype, {
			refresh: function(frm) {
				if (['Loan Disbursement', 'Loan Repayment', 'Loan Interest Accrual', 'Loan Write Off'].includes(frm.doc.doctype)
					&& frm.doc.docstatus > 0) {
					cur_frm.add_custom_button(__('Accounting Ledger'), function() {
						frappe.route_options = {
							voucher_no: frm.doc.name,
							from_date: frm.doc.posting_date,
							to_date: frm.doc.posting_date,
							company: frm.doc.company,
							group_by: "Group by Voucher (Consolidated)",
							show_cancelled_entries: frm.doc.docstatus === 2
						};
						frappe.set_route("query-report", "General Ledger");
					}, __("View"));
				}
				erpnext.hide_company();
				frm.trigger("set_company_filter");
			},
			applicant_type: function(frm) {
				frm.trigger("set_company_filter");
			},
			set_company_filter: function(frm) {
				if (["Loan Application", "Loan"].includes(frm.doc.doctype)) {
					if (frm.doc.applicant_type === "Employee") {
						frm.set_query("applicant", function() {
							return {
								"filters": {
									"company": frm.doc.company
								}
							};
						});
					} else {
						frm.set_query("applicant", function() {
							return {
								"filters": {
									"docstatus": 0
								}
							};
						});
					}
				}
			},

			applicant: function(frm) {
				if (!["Loan Application", "Loan"].includes(frm.doc.doctype)) {
					return;
				}

				if (frm.doc.applicant) {
					frappe.model.with_doc(frm.doc.applicant_type, frm.doc.applicant, function() {
						var applicant = frappe.model.get_doc(frm.doc.applicant_type, frm.doc.applicant);
						frm.set_value("applicant_name",
							applicant.employee_name || applicant.member_name);
					});
				}
				else {
					frm.set_value("applicant_name", null);
				}
			}
		});
	}
}