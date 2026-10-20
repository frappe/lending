// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lending Settings", {
	refresh(frm) {
		load_mutual_fund_adapters(frm);
	},
});

function load_mutual_fund_adapters(frm) {
	frappe.call({
		method: "lending.collateral.mutual_fund.registry.adapter_choices",
		type: "GET",
		callback(r) {
			Object.entries(r.message || {}).forEach(([fieldname, keys]) => {
				// The empty choice turns the integration off
				const choices = ["", ...keys];

				// Keeps a saved adapter whose app is gone, so the form still shows what is set
				if (frm.doc[fieldname] && !choices.includes(frm.doc[fieldname])) {
					choices.push(frm.doc[fieldname]);
				}

				frm.set_df_property(fieldname, "options", choices.join("\n"));
			});
		},
	});
}
