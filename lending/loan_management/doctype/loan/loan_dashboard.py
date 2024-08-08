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
					"Loan Security Assignment",
					"Loan Security Shortfall",
					"Loan Disbursement",
					"Loan Demand",
				]
			},
			{
				"items": [
					"Loan Repayment",
					"Loan Interest Accrual",
					"Loan Write Off",
					"Loan Restructure",
					"Loan Refund",
					"Loan Freeze Log",
				]
			},
			{
				"items": [
					"Loan Security Release",
					"Days Past Due Log",
					"Loan NPA Log",
					"Journal Entry",
					"Sales Invoice",
					"Loan Limit Change Log",
				]
			},
		],
	}
