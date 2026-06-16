def get_data():
	return {
		"fieldname": "loan_disbursement",
		"transactions": [
			{
				"label": "Schedule",
				"items": ["Loan Repayment Schedule", "Loan Security Deposit"],
			},
			{
				"label": "Repayment",
				"items": ["Loan Demand", "Loan Interest Accrual", "Loan Repayment", "Bulk Repayment Log"],
			},
			{
				"label": "Adjustments",
				"items": ["Loan Restructure", "Loan Write Off", "Loan Adjustment", "Loan Repayment Repost"],
			},
			{
				"label": "Logs",
				"items": ["Days Past Due Log"],
			},
		],
	}
