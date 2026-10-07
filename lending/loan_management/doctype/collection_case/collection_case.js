// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on('Collection Case', {
	refresh: function(frm) {
		if (frm.doc.linked_restructure || ['Resolved', 'Closed'].includes(frm.doc.status)) {
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
