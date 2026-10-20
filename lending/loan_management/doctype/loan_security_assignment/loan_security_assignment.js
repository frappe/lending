// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const MF_REGISTRY = "lending.collateral.mutual_fund.registry";

frappe.ui.form.on('Loan Security Assignment', {
	setup: function(frm) {
		frm.set_query("mutual_fund_holding", "securities", function(doc, cdt, cdn) {
			let row = locals[cdt][cdn];
			return {
				filters: {
					applicant_type: doc.applicant_type,
					applicant: doc.applicant,
					loan_security: row.loan_security,
				}
			};
		});
	},

	refresh: function(frm) {
		if (frm.doc.status === "Release Requested") {
			frm.add_custom_button(__("Release"), function() {
				frm.trigger("release_loan_security_assignment");
			})
		}
		add_mutual_fund_buttons(frm);
	},

	calculate_amounts: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, 'amount', row.qty * row.loan_security_price);
		frappe.model.set_value(cdt, cdn, 'post_haircut_amount', cint(row.amount - (row.amount * row.haircut/100)));

		let amount = 0;
		let maximum_amount = 0;
		$.each(frm.doc.securities || [], function(i, item){
			amount += item.amount;
			maximum_amount += item.post_haircut_amount;
		});

		frm.set_value('total_security_value', amount);
		frm.set_value('maximum_loan_value', maximum_amount);
	},

	release_loan_security_assignment: function(frm) {
		frappe.confirm(__("Do you really want to release this loan security assignment?"), function () {
			frappe.call({
				args: {
					"loan_security_assignment": frm.doc.name,
				},
				method: "lending.loan_management.doctype.loan_security_assignment.loan_security_assignment.release_loan_security_assignment",
				callback: function(r) {
					frm.reload_doc();
				}
			})
		})
	},
});

frappe.ui.form.on("Pledge", {
	loan_security: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];

		if (row.loan_security) {
			frappe.call({
				method: "lending.loan_management.doctype.loan_security.loan_security.get_loan_security_price_or_value",
				args: {
					loan_security: row.loan_security
				},
				callback: function(r) {
					if (r.message['qty']) {
						frappe.model.set_value(cdt, cdn, 'qty', r.message['qty']);
					}

					frappe.model.set_value(cdt, cdn, 'loan_security_price', r.message['value']);
					frm.events.calculate_amounts(frm, cdt, cdn);
				}
			});
		}
	},

	qty: function(frm, cdt, cdn) {
		frm.events.calculate_amounts(frm, cdt, cdn);
	},

	loan_security_price: function(frm, cdt, cdn) {
		frm.events.calculate_amounts(frm, cdt, cdn);
	},
});

function add_mutual_fund_buttons(frm) {
	const before_pledge =
		!frm.is_new() &&
		(frm.doc.docstatus === 0 || (frm.doc.docstatus === 1 && frm.doc.status === "Pledge Requested"));
	if (!before_pledge) return;

	frappe.call({ method: `${MF_REGISTRY}.get_setup`, type: "GET" }).then(({ message }) => {
		if (!message?.registry) return;
		const group = __("Mutual Fund");

		frm.add_custom_button(__("Fetch Holdings"), () => fetch_holdings(frm), group);

		const has_lien_lines = (frm.doc.securities || []).some(
			(row) => row.is_mutual_fund && row.holding_mode === "Statement of Account"
		);
		if (!has_lien_lines || frm.doc.lien_status === "Marked") return;

		frm.add_custom_button(__("Request Lien"), () => request_lien(frm), group);
		if (frm.doc.lien_status === "OTP Sent") {
			frm.add_custom_button(__("Confirm Lien"), () => confirm_lien(frm), group);
		}
	});
}

function saved(frm) {
	return frm.is_dirty() ? frm.save() : Promise.resolve();
}

function fetch_holdings(frm) {
	saved(frm).then(() => {
		frappe.db
			.get_value("Customer", frm.doc.applicant, ["tax_id", "mobile_no"])
			.then(({ message }) => ask_for_consent(frm, message || {}));
	});
}

function ask_for_consent(frm, customer) {
	let request_id = null;
	const dialog = new frappe.ui.Dialog({
		title: __("Fetch Mutual Fund Holdings"),
		fields: [
			{ fieldname: "pan", fieldtype: "Data", label: __("PAN"), reqd: 1, default: customer.tax_id },
			{ fieldname: "mobile", fieldtype: "Data", label: __("Mobile"), reqd: 1, default: customer.mobile_no },
			{
				fieldname: "otp",
				fieldtype: "Data",
				label: __("OTP"),
				description: __("Sent by the registry to the borrower, to consent to reading their folios"),
				hidden: 1,
			},
		],
		primary_action_label: __("Send OTP"),
		primary_action(values) {
			if (!request_id) {
				frappe
					.call({
						method: `${MF_REGISTRY}.send_holdings_otp`,
						args: { loan_security_assignment: frm.doc.name, pan: values.pan, mobile: values.mobile },
						freeze: true,
					})
					.then(({ message }) => {
						if (!message) return;
						request_id = message.request_id;
						dialog.set_df_property("otp", "hidden", 0);
						dialog.set_df_property("otp", "reqd", 1);
						dialog.set_df_property("pan", "read_only", 1);
						dialog.set_df_property("mobile", "read_only", 1);
						dialog.set_primary_action(__("Fetch Holdings"), dialog.primary_action);
					});
				return;
			}
			frappe
				.call({
					method: `${MF_REGISTRY}.fetch_holdings`,
					args: {
						loan_security_assignment: frm.doc.name,
						pan: values.pan,
						request_id,
						otp: values.otp,
					},
					freeze: true,
					freeze_message: __("Reading folios..."),
				})
				.then(({ message }) => {
					if (!message) return;
					dialog.hide();
					select_holdings(frm, message);
				});
		},
	});
	dialog.show();
}

function get_lot_rows(holdings) {
	const today = frappe.datetime.get_today();
	const rows = [];
	holdings.forEach((holding) => {
		let free = flt(holding.free_units);
		holding.lots.forEach((lot) => {
			const available = Math.min(flt(lot.units), free);
			free -= available;

			let remark = "";
			if (!holding.loan_security) {
				remark = __("Not an approved security");
			} else if (holding.lock_in_days) {
				const unlocks = frappe.datetime.add_days(lot.purchase_date, holding.lock_in_days);
				if (unlocks > today) remark = __("Locked in until {0}", [frappe.datetime.str_to_user(unlocks)]);
			}
			if (!remark && available <= 0) remark = __("Already pledged");

			rows.push({
				scheme_name: holding.scheme_name,
				loan_security: holding.loan_security,
				folio_number: holding.folio_number,
				holding_mode: holding.holding_mode,
				holding_type: holding.holding_type,
				units: holding.units,
				purchase_date: lot.purchase_date,
				free_units: available,
				qty: remark ? 0 : available,
				remark: remark || __("Can be pledged"),
				can_pledge: !remark,
			});
		});
	});
	return rows;
}

function select_holdings(frm, holdings) {
	const rows = get_lot_rows(holdings);
	const dialog = new frappe.ui.Dialog({
		title: __("Select Units to Pledge"),
		size: "extra-large",
		fields: [
			{
				fieldname: "holdings",
				fieldtype: "Table",
				cannot_add_rows: 1,
				cannot_delete_rows: 1,
				in_place_edit: 1,
				data: rows,
				fields: [
					{ fieldname: "scheme_name", fieldtype: "Data", label: __("Scheme"), in_list_view: 1, read_only: 1, columns: 3 },
					{ fieldname: "folio_number", fieldtype: "Data", label: __("Folio"), in_list_view: 1, read_only: 1, columns: 2 },
					{ fieldname: "purchase_date", fieldtype: "Date", label: __("Bought On"), in_list_view: 1, read_only: 1, columns: 1 },
					{ fieldname: "free_units", fieldtype: "Float", label: __("Free Units"), in_list_view: 1, read_only: 1, columns: 1 },
					{ fieldname: "qty", fieldtype: "Float", label: __("Units to Pledge"), in_list_view: 1, columns: 1 },
					{ fieldname: "remark", fieldtype: "Data", label: __("Status"), in_list_view: 1, read_only: 1, columns: 2 },
				],
			},
		],
		primary_action_label: __("Add to Pledge"),
		primary_action() {
			const lines = dialog.fields_dict.holdings.grid
				.get_selected_children()
				.filter((row) => row.can_pledge && flt(row.qty) > 0);
			if (!lines.length) {
				frappe.msgprint(__("Select at least one lot that can be pledged"));
				return;
			}
			frappe
				.call({
					method: `${MF_REGISTRY}.add_holdings`,
					args: { loan_security_assignment: frm.doc.name, lines },
					freeze: true,
				})
				.then(() => {
					dialog.hide();
					frm.reload_doc();
				});
		},
	});
	dialog.show();
}

function request_lien(frm) {
	saved(frm).then(() =>
		frappe
			.call({
				method: `${MF_REGISTRY}.request_lien`,
				args: { loan_security_assignment: frm.doc.name },
				freeze: true,
			})
			.then(({ message }) => {
				if (!message) return;
				frappe.show_alert({ message: __("Lien requested. The borrower gets an OTP to approve it"), indicator: "blue" });
				frm.reload_doc();
			})
	);
}

function confirm_lien(frm) {
	frappe.prompt(
		{ fieldname: "otp", fieldtype: "Data", label: __("OTP from the Borrower"), reqd: 1 },
		({ otp }) =>
			frappe
				.call({
					method: `${MF_REGISTRY}.confirm_lien`,
					args: { loan_security_assignment: frm.doc.name, otp },
					freeze: true,
				})
				.then(({ message }) => {
					if (!message) return;
					frappe.show_alert({ message: __("Lien marked"), indicator: "green" });
					frm.reload_doc();
				}),
		__("Confirm Lien"),
		__("Confirm")
	);
}
