// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Vehicle Valuation", {
	setup(frm) {
		frm.set_query("vehicle", () => ({
			filters: { status: "Proposed", asset_condition: ["!=", "New"] },
		}));
	},
});
