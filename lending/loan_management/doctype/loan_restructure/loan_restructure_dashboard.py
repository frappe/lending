def get_data():
	return {
		"fieldname": "loan_restructure",
		"non_standard_fieldnames": {
			"Loan Balance Adjustment": "reference_name",
		},
		"transactions": [
			{"items": ["Loan Repayment Schedule", "Loan Repayment"]},
		],
	}
