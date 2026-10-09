// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on('Collection Case', {
	refresh: function(frm) {
		if (frm.doc.linked_restructure || ['Resolved', 'Closed'].includes(frm.doc.status)) {
			return;
		}
		// launch_hardship also creates a Loan Repayment Schedule internally, which
		// only Loan Manager / System Manager can do -- hide the button for anyone
		// who can't actually complete the action instead of letting it fail server-side.
		if (!frappe.perm.has_perm('Loan Restructure', 0, 'create')) {
			return;
		}

		frm.add_custom_button(__('Hardship / Restructure'), function() {
			frappe.prompt(
				[
					{
						fieldname: 'restructure_type',
						fieldtype: 'Select',
						label: __('Restructure Type'),
						options: ['Normal Restructure', 'Pre Payment', 'Advance Payment'],
						reqd: 1,
						default: 'Normal Restructure',
					},
				],
				function(values) {
					frappe.call({
						method: 'lending.loan_management.collections.launch_hardship',
						args: {
							case_name: frm.doc.name,
							restructure_type: values.restructure_type,
						},
						freeze: true,
						callback: function() {
							frm.reload_doc();
						},
					});
				},
				__('Launch Hardship Restructure'),
				__('Create')
			);
		}, __('Create'));
	},
});
