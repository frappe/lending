// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const ADAPTER_FIELDS = {
	credit_bureau_adapter: "Credit Bureau",
	pan_verification_adapter: "PAN Verification",
	kyc_adapter: "KYC",
	bank_verification_adapter: "Bank Account Verification",
	esign_adapter: "eSign",
};

frappe.ui.form.on("Loan Origination Settings", {
	refresh(frm) {
		Object.entries(ADAPTER_FIELDS).forEach(([fieldname, provider_type]) =>
			load_adapters(frm, fieldname, provider_type)
		);
	},
});

function load_adapters(frm, fieldname, provider_type) {
	frappe.call({
		method: "lending.loan_integrations.adapters.adapter_choices",
		type: "GET",
		args: { provider_type },
		callback(r) {
			// The empty choice turns the integration off.
			const choices = ["", ...(r.message || [])];

			// Keeps a saved adapter whose app is gone, so the form still shows what is set.
			if (frm.doc[fieldname] && !choices.includes(frm.doc[fieldname])) {
				choices.push(frm.doc[fieldname]);
			}

			frm.set_df_property(fieldname, "options", choices.join("\n"));
		},
	});
}
