// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Process Loan Statement of Accounts", {
	refresh: function (frm) {
		if (!frm.doc.__islocal) {
			frm.add_custom_button(__("Send Emails"), function () {
				if (frm.is_dirty()) frappe.throw(__("Please save before proceeding."));
				frappe.call({
					method: "lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts.send_emails",
					args: { document_name: frm.doc.name },
					callback: function (r) {
						if (r && r.message) {
							frappe.show_alert({ message: __("Emails Queued"), indicator: "blue" });
						} else {
							frappe.msgprint(__("No Records for these settings."));
						}
					},
				});
			});

			frm.add_custom_button(__("Download"), function () {
				if (frm.is_dirty()) frappe.throw(__("Please save before proceeding."));
				let url = frappe.urllib.get_full_url(
					"/api/method/lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts.download_statements?" +
						"document_name=" +
						encodeURIComponent(frm.doc.name)
				);
				$.ajax({
					url: url,
					type: "GET",
					success: function (result) {
						if (jQuery.isEmptyObject(result)) {
							frappe.msgprint(__("No Records for these settings."));
						} else {
							window.location = url;
						}
					},
				});
			});
		}
		frm.trigger("set_collection_label");
	},

	onload: function (frm) {
		if (frm.doc.__islocal) {
			frm.set_value("from_date", frappe.datetime.add_months(frappe.datetime.get_today(), -12));
			frm.set_value("to_date", frappe.datetime.get_today());
		}
		frm.set_query("loan_product", function () {
			return { filters: { company: frm.doc.company } };
		});
	},

	set_collection_label: function (frm) {
		let label = __("Select {0}s By", [frm.doc.applicant_type || __("Applicant")]);
		frm.get_field("collection_based_on").set_label(label);
	},

	applicant_type: function (frm) {
		frm.clear_table("applicants");
		frm.refresh_field("applicants");
		frm.trigger("set_collection_label");
	},

	fetch_applicants: function (frm) {
		if (!frm.doc.collection_based_on) {
			frappe.throw(__("Please select how to collect Applicants."));
		}
		frappe.call({
			method: "lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts.fetch_applicants",
			args: {
				company: frm.doc.company,
				applicant_type: frm.doc.applicant_type,
				collection_based_on: frm.doc.collection_based_on,
				loan_product: frm.doc.loan_product,
			},
			callback: function (r) {
				if (!r.exc) {
					if (r.message && r.message.length) {
						frm.clear_table("applicants");
						for (const applicant of r.message) {
							let row = frm.add_child("applicants");
							row.applicant_type = applicant.applicant_type;
							row.applicant = applicant.applicant;
							row.applicant_name = applicant.applicant_name;
							row.email = applicant.email;
						}
						frm.refresh_field("applicants");
					} else {
						frappe.throw(__("No Applicants found with selected options."));
					}
				}
			},
		});
	},
});

frappe.ui.form.on("Process Loan Statement of Accounts Applicant", {
	applicant: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.applicant || !row.applicant_type) {
			return;
		}
		frappe.call({
			method: "lending.loan_management.doctype.process_loan_statement_of_accounts.process_loan_statement_of_accounts.get_applicant_details",
			args: {
				applicant_type: row.applicant_type,
				applicant: row.applicant,
			},
			callback: function (r) {
				if (r.message) {
					frappe.model.set_value(cdt, cdn, "applicant_name", r.message.applicant_name);
					frappe.model.set_value(cdt, cdn, "email", r.message.email);
				}
			},
		});
	},
});
