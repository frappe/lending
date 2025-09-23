frappe.ui.form.on('Customer', {

	refresh: function (frm) {
		if (!frm.doc.is_npa) {
				frm.add_custom_button(__('Loan Application'), function() {
					frappe.new_doc('Loan Application', {
						applicant_type: 'Customer',
						applicant: frm.doc.name,

					}
				)
			}, __('Create'));
		}
	}
});
