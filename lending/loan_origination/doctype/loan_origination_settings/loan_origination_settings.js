// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Origination Settings", {
	refresh(frm) {
		load_credit_bureau_adapters(frm);
	},
});

function load_credit_bureau_adapters(frm) {
	frappe.call({
		method: "lending.loan_integrations.adapters.adapter_choices",
		type: "GET",
		args: { provider_type: "Credit Bureau" },
		callback(r) {
			// The empty choice turns bureau pulls off.
			const choices = ["", ...(r.message || [])];

			// Keeps a saved adapter whose app is gone, so the form still shows what is set.
			if (frm.doc.credit_bureau_adapter && !choices.includes(frm.doc.credit_bureau_adapter)) {
				choices.push(frm.doc.credit_bureau_adapter);
			}

			frm.set_df_property("credit_bureau_adapter", "options", choices.join("\n"));
		},
	});
}
