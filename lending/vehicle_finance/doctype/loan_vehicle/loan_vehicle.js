// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Vehicle", {
	setup(frm) {
		frm.set_query("loan_security_type", () => ({ filters: { is_vehicle: 1 } }));
		frm.set_query("vehicle_model", () => ({ filters: { disabled: 0 } }));
		frm.set_query("applicant_type", () => ({
			filters: { name: ["in", ["Customer", "Employee"]] },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.status === "Proposed" && frm.doc.asset_condition !== "New") {
			frm.add_custom_button(
				__("Vehicle Valuation"),
				() => frappe.new_doc("Vehicle Valuation", { vehicle: frm.doc.name }),
				__("Create")
			);
		}

		if (frm.doc.status === "Proposed") {
			frm.add_custom_button(
				__("Cancel Vehicle"),
				() => frm.events.call_action(frm, "cancel_vehicle"),
				__("Status")
			);
		}

		if (frm.doc.status === "Financed") {
			frm.add_custom_button(
				__("Mark Repossessed"),
				() => frm.events.call_action(frm, "mark_repossessed"),
				__("Status")
			);
		}

		if (
			["Released", "Sold"].includes(frm.doc.status) &&
			frm.doc.hypothecation_status !== "Terminated"
		) {
			frm.add_custom_button(
				__("Mark Hypothecation Terminated"),
				() => {
					frappe.prompt(
						{
							fieldname: "termination_date",
							fieldtype: "Date",
							label: __("Termination Date"),
							default: frappe.datetime.get_today(),
							reqd: 1,
						},
						(values) =>
							frm.events.call_action(frm, "mark_hypothecation_terminated", values),
						__("New RC without hypothecation received")
					);
				},
				__("Status")
			);
		}
	},

	call_action(frm, method, args = {}) {
		frappe.call({
			method: `lending.vehicle_finance.doctype.loan_vehicle.loan_vehicle.${method}`,
			args: { vehicle: frm.doc.name, ...args },
			freeze: true,
			callback: () => frm.reload_doc(),
		});
	},
});
