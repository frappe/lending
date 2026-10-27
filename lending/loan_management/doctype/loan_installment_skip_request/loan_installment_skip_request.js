// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const INSTALLMENTS_PATH =
	"lending.loan_management.doctype.loan_restructure.installment_skip";

frappe.ui.form.on("Loan Installment Skip Request", {
	setup(frm) {
		frm.set_query("loan", () => ({ query: `${INSTALLMENTS_PATH}.search_skippable_loans` }));
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;

		if (!frm.is_new() && frm.doc.status === "Open") {
			frm.add_custom_button(__("Select Installments"), () => frm.trigger("select_installments"));
			frm.trigger("add_decision_buttons");
		}
	},

	loan(frm) {
		frm.clear_table("skipped_installments");
		frm.refresh_field("skipped_installments");

		if (frm.doc.loan) frm.trigger("select_installments");
	},

	add_decision_buttons(frm) {
		const roles = frappe.user_roles;
		const can_decide =
			frappe.session.user === frm.doc.approver ||
			roles.includes("Loan Manager") ||
			roles.includes("System Manager");

		if (!can_decide) return;

		frm.add_custom_button(__("Approve"), () => decide(frm, "Approved"), __("Decision"));
		frm.add_custom_button(__("Reject"), () => decide(frm, "Rejected"), __("Decision"));
	},

	select_installments(frm) {
		if (!frm.doc.loan) {
			frappe.msgprint(__("Please select a Loan first."));
			return;
		}

		frappe.call({
			method: `${INSTALLMENTS_PATH}.get_upcoming_installments`,
			args: { loan: frm.doc.loan },
		}).then((r) => {
			const installments = r.message || [];
			if (!installments.length) {
				frappe.msgprint(__("There are no upcoming installments to skip."));
				return;
			}

			const selected = (frm.doc.skipped_installments || []).map((row) => row.payment_date);
			const dialog = new frappe.ui.Dialog({
				title: __("Installments to Skip"),
				fields: [
					{
						fieldname: "dates",
						fieldtype: "MultiCheck",
						columns: 2,
						sort_options: false,
						options: installments.map((row) => ({
							label: `${frappe.datetime.str_to_user(row.payment_date)} (${format_currency(row.total_payment)})`,
							value: row.payment_date,
							checked: selected.includes(row.payment_date),
						})),
					},
				],
				primary_action_label: __("Select"),
				primary_action: (values) => {
					frm.clear_table("skipped_installments");
					(values.dates || []).forEach((date) => {
						frm.add_child("skipped_installments", { payment_date: date });
					});
					frm.refresh_field("skipped_installments");
					dialog.hide();
				},
			});
			dialog.show();
		});
	},
});

function decide(frm, status) {
	frm.set_value("status", status);
	frm.save("Submit");
}
