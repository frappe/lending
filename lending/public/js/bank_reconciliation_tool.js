frappe.provide("erpnext.accounts.bank_reconciliation.voucher_types");

erpnext.accounts.bank_reconciliation.voucher_types["Loan Repayment"] = {
	is_applicable(bank_transaction) {
		return bank_transaction.deposit > 0;
	},

	get_fields(dialog_manager) {
		const show =
			"eval:doc.action=='Create Voucher' && doc.document_type=='Loan Repayment'";
		return [
			{
				fieldname: "against_loan",
				fieldtype: "Link",
				label: __("Loan"),
				options: "Loan",
				depends_on: show,
				mandatory_depends_on: show,
				get_query: () => {
					const values = dialog_manager.dialog.get_values(true);
					const filters = {
						docstatus: 1,
						company: dialog_manager.company,
						status: [
							"not in",
							["Draft", "Sanctioned", "Closed", "Settled"],
						],
					};
					if (values.party_type && values.party) {
						filters.applicant_type = values.party_type;
						filters.applicant = values.party;
					}
					return { filters };
				},
			},
			{
				fieldname: "repayment_type",
				fieldtype: "Select",
				label: __("Repayment Type"),
				options: [
					"Normal Repayment",
					"Advance Payment",
					"Pre Payment",
					"Loan Closure",
					"Partial Settlement",
					"Full Settlement",
					"Write Off Recovery",
				].join("\n"),
				default: "Normal Repayment",
				depends_on: show,
				mandatory_depends_on: show,
			},
			{
				fieldname: "loan_disbursement",
				fieldtype: "Link",
				label: __("Loan Disbursement"),
				options: "Loan Disbursement",
				depends_on: `${show} && doc.against_loan`,
				get_query: () => {
					return {
						filters: {
							docstatus: 1,
							against_loan:
								dialog_manager.dialog.get_value("against_loan"),
						},
					};
				},
			},
		];
	},

	create(dialog_manager, values, allow_edit) {
		return frappe.xcall(
			"lending.loan_management.doctype.loan_repayment.loan_repayment.create_loan_repayment_bts",
			{
				bank_transaction_name: dialog_manager.bank_transaction.name,
				against_loan: values.against_loan,
				repayment_type: values.repayment_type,
				loan_disbursement: values.loan_disbursement,
				reference_number: values.reference_number,
				reference_date: values.reference_date,
				posting_date: values.posting_date,
				mode_of_payment: values.mode_of_payment,
				cost_center: values.cost_center,
				allow_edit: allow_edit,
			},
		);
	},
};
