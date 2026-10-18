// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Security Sale", {
	setup(frm) {
		frm.set_query("loan", () => ({
			filters: { docstatus: 1, is_secured_loan: 1 },
		}));
		frm.set_query("loan_security_shortfall", () => ({
			filters: { loan: frm.doc.loan },
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.loan) {
			frm.add_custom_button(__("Prefill Items"), () => frm.call("prefill_items"));
		}

		if (frm.doc.docstatus === 1 && frm.doc.status === "Sold") {
			frm.add_custom_button(__("Apply Proceeds"), () => {
				// A sale held back by a moratorium is applied later, on a date past its end
				frappe.prompt(
					{
						fieldname: "proceeds_date",
						fieldtype: "Date",
						label: __("Proceeds Date"),
						default: frm.doc.posting_date,
						reqd: 1,
					},
					({ proceeds_date }) =>
						frm
							.call({
								method: "apply_proceeds",
								doc: frm.doc,
								args: { proceeds_date },
								freeze: true,
							})
							.then(() => frm.reload_doc()),
					__("Apply Proceeds"),
					__("Apply")
				);
			});
		}
	},

	deductions(frm) {
		set_net_proceeds(frm);
	},

	charges(frm) {
		set_net_proceeds(frm);
	},
});

frappe.ui.form.on("Loan Security Sale Item", {
	sold_qty(frm, cdt, cdn) {
		set_proceeds(frm, cdt, cdn);
	},

	sale_price(frm, cdt, cdn) {
		set_proceeds(frm, cdt, cdn);
	},
});

function set_proceeds(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "proceeds", flt(row.sold_qty) * flt(row.sale_price));

	const gross = (frm.doc.items || []).reduce((total, item) => total + flt(item.proceeds), 0);
	frm.set_value("gross_proceeds", gross);
	set_net_proceeds(frm);
}

function set_net_proceeds(frm) {
	frm.set_value(
		"net_proceeds",
		flt(frm.doc.gross_proceeds) - flt(frm.doc.deductions) - flt(frm.doc.charges)
	);
}
