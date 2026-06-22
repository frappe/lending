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
				"label": "Schedule & Disbursement",
				"items": [
					"Loan Repayment Schedule",
					"Loan Disbursement",
					"Loan Demand",
				],
			},
			{
				"label": "Repayment",
				"items": [
					"Loan Repayment",
					"Loan Interest Accrual",
					"Loan Refund",
					"Loan Repayment Repost",
				],
			},
			{
				"label": "Security",
				"items": [
					"Loan Security Assignment",
					"Loan Security Shortfall",
					"Loan Security Deposit",
					"Loan Security Release",
				],
			},
			{
				"label": "Adjustments",
				"items": [
					"Loan Restructure",
					"Loan Write Off",
					"Loan Adjustment",
					"Loan Balance Adjustment",
				],
			},
			{
				"label": "Logs",
				"items": [
					"Days Past Due Log",
					"Loan NPA Log",
					"Loan Freeze Log",
					"Loan Limit Change Log",
				],
			},
			{
				"label": "Accounting",
				"items": [
					"Journal Entry",
					"Sales Invoice",
				],
			},
		],
	}
