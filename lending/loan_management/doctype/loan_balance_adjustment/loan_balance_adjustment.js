// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Balance Adjustment', {
	refresh: function(frm) {
		if (frm.doc.docstatus == 1) {
			frm.add_custom_button(__("Accounting Ledger"), function() {
				frappe.route_options = {
					voucher_no: frm.doc.name,
					company: frm.doc.company,
					from_date: moment(frm.doc.posting_date).format('YYYY-MM-DD'),
					to_date: moment(frm.doc.posting_date).format('YYYY-MM-DD'),
				};

				frappe.set_route("query-report", "General Ledger");
			},__("View"));
		}
	}
});