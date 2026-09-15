// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Integration Provider", {
	refresh(frm) {
		// Only fills the dropdown. A refresh happens after every save, so anything that touched
		// the document here would leave the form dirty against a document nothing had changed in.
		load_adapter_choices(frm);
	},

	provider_type(frm) {
		// A real change by a person, so an adapter that does not serve the new type may go.
		load_adapter_choices(frm, { drop_incompatible_adapter: true });
	},
});

function load_adapter_choices(frm, { drop_incompatible_adapter = false } = {}) {
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

			if (frm.doc.adapter && !choices.includes(frm.doc.adapter)) {
				if (drop_incompatible_adapter) {
					frm.set_value("adapter", "");
				} else {
					// Keep what is saved in the list. Giving a Select options that do not include
					// its own value blanks the control, and that reads as an edit nobody made.
					choices.push(frm.doc.adapter);
				}
			}

			frm.set_df_property("adapter", "options", choices.join("\n"));
		},
	});
}
