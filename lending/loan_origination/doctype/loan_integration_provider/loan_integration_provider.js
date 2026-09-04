// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Integration Provider", {
	refresh(frm) {
		frm.trigger("provider_type");
	},

	provider_type(frm) {
		if (!frm.doc.provider_type) {
			frm.set_df_property("adapter", "options", "");
			return;
		}

		frappe.call({
			method: "lending.loan_integrations.adapters.adapter_choices",
			type: "GET",
			args: { provider_type: frm.doc.provider_type },
			callback(r) {
				const choices = r.message || [];
				frm.set_df_property("adapter", "options", choices.join("\n"));

				// The chosen adapter may not serve the newly chosen provider type.
				if (frm.doc.adapter && !choices.includes(frm.doc.adapter)) {
					frm.set_value("adapter", "");
				}
			},
		});
	},
});
