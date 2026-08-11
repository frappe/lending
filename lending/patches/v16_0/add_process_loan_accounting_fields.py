from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "loan_gl_consolidation",
					"label": "Consolidate Loan GL Monthly",
					"description": "Post a single consolidated GL voucher per month for Loan Interest Accrual and Loan Demand instead of one per accrual/demand. Daily accrual computation is unaffected.",
					"fieldtype": "Check",
					"insert_after": "async_gl_reversal_start_date",
				},
				{
					"fieldname": "loan_gl_consolidation_start_date",
					"label": "Loan GL Consolidation Start Date",
					"fieldtype": "Date",
					"depends_on": "loan_gl_consolidation",
					"mandatory_depends_on": "loan_gl_consolidation",
					"description": "Only accruals and demands with posting date on or after this date are deferred and consolidated. Earlier entries keep their daily GL.",
					"insert_after": "loan_gl_consolidation",
				},
			],
			"Journal Entry": [
				{
					"fieldname": "process_loan_accounting_voucher",
					"fieldtype": "Link",
					"label": "Process Loan Accounting Voucher",
					"insert_after": "loan",
					"options": "Process Loan Accounting",
					"search_index": 1,
					"no_copy": 1,
					"read_only": 1,
				},
				{
					"fieldname": "process_loan_accounting_month_end",
					"fieldtype": "Date",
					"label": "Process Loan Accounting Month End",
					"insert_after": "process_loan_accounting_voucher",
					"search_index": 1,
					"no_copy": 1,
					"read_only": 1,
				},
			],
		},
		update=True,
	)
