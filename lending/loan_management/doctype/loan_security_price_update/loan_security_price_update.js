// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Security Price Update", {
	setup(frm) {
		frm.set_query("loan_security", "items", () => ({
			filters: { loan_security_type: frm.doc.loan_security_type, disabled: 0 },
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.loan_security_type) {
			frm.add_custom_button(__("Get Securities"), () => frm.call("get_securities"));
			add_read_nav_file_button(frm);
		}
	},

	loan_security_type(frm) {
		frm.refresh();
	},
});

function add_read_nav_file_button(frm) {
	frappe.db
		.get_value("Loan Security Type", frm.doc.loan_security_type, "is_mutual_fund")
		.then(({ message }) => {
			if (message?.is_mutual_fund) {
				frm.add_custom_button(__("Read AMFI NAV File"), () => read_nav_file(frm));
			}
		});
}

function read_nav_file(frm) {
	// The server attaches the file once the update is saved, so a new update keeps it too
	new frappe.ui.FileUploader({
		restrictions: { allowed_file_types: [".txt"] },
		on_success(file) {
			frappe
				.call({
					method: "lending.collateral.mutual_fund.nav_file.read_nav_file",
					args: { doc: frm.doc, file_name: file.name },
					freeze: true,
					freeze_message: __("Reading NAV file..."),
				})
				.then(({ message }) => {
					if (frm.is_new()) {
						frappe.set_route("Form", frm.doctype, message.name);
					} else {
						frm.reload_doc();
					}
					if (message.filled) {
						frappe.show_alert({
							message: __("Filled {0} prices from the NAV file", [message.filled]),
							indicator: "green",
						});
					}
				});
		},
	});
}
