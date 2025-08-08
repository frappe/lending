// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Process Loan Classification", {
// 	refresh(frm) {

// 	},
// });
let active_loan_filters = {
					"docstatus": 1,
					"status": ["not in", ["Closed", "Draft", "Settled", "Written Off"]],
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
frappe.ui.form.on('Process Loan Classification', {
	onload: function (frm) {
		set_loan_filters(frm, active_loan_filters)
	},
	loan_product: function (frm) {
		if (frm.doc.loan_product) {
			active_loan_filters["loan_product"] = frm.doc.loan_product
			set_loan_filters(frm, active_loan_filters)
		}
		else {
			set_loan_filters(frm, active_loan_filters)
		}
	},
	loan: function (frm) {
		if (frm.doc.loan) {
			set_loan_disbursement_filters(frm, {"against_loan": frm.doc.loan})
		}
		else {
			set_loan_disbursement_filters(frm, {})
		}
	},
	loan_disbursement: function(frm) {
		frappe.db.get_value("Loan Disbursement", {"name": frm.doc.loan_disbursement}, ["against_loan"])
			.then(
				resp => {
					frm.set_value("loan", resp.message.against_loan)
				}
			)
	}
});
