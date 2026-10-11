// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loan Security', {
	refresh: function(frm) {
		frm.trigger('show_ltv_before_upgrade');
	},

	loan_security_type: function(frm) {
		frm.trigger('follow_type_haircut');
	},

	override_haircut: function(frm) {
		frm.trigger('follow_type_haircut');
	},

	haircut: function(frm) {
		frm.set_value('loan_to_value_ratio', 100 - flt(frm.doc.haircut));
	},

	follow_type_haircut: function(frm) {
		if (frm.doc.override_haircut || !frm.doc.loan_security_type) return;

		frappe.db.get_value('Loan Security Type', frm.doc.loan_security_type, 'haircut').then(r => {
			frm.set_value('haircut', r.message.haircut);
		});
	},

	show_ltv_before_upgrade: function(frm) {
		const typed = flt(frm.doc.ltv_before_upgrade);
		if (!typed || frm.doc.override_haircut) return;

		const current = flt(frm.doc.loan_to_value_ratio);
		frm.set_intro(
			__('Before the upgrade, this security\'s LTV was typed as {0}%. Per-loan limits used the type\'s {1}%, but the applicant-wise limit used {0}%. It now follows the type at {1}%. To keep {0}%, tick Override Haircut and set the haircut to {2}.',
				[typed, current, 100 - typed]),
			'orange'
		);

		frm.add_custom_button(__('Keep {0}%', [current]), () => {
			frm.set_value('ltv_before_upgrade', null);
			frm.save();
		});
	},
});
