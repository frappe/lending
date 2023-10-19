def get_data():
	return {
		"fieldname": "loan",
		"non_standard_fieldnames": {
			"Loan Disbursement": "against_loan",
			"Loan Repayment": "against_loan",
			"Journal Entry": "reference_name",
		},
		"transactions": [
			{
				"items": [
					"Loan Repayment Schedule",
					"Loan Collateral Assignment",
					"Loan Security Shortfall",
					"Loan Disbursement",
				]
			},
			{"items": ["Loan Repayment", "Loan Interest Accrual", "Loan Write Off", "Loan Restructure"]},
			{
				"items": [
					"Loan Collateral Deassignment",
					"Days Past Due Log",
					"Journal Entry",
					"Sales Invoice",
				]
			},
		],
	}
