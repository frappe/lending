def update_value_date_in_gl_dict(doc, gl_dict):
	if doc.get("value_date"):
		gl_dict["value_date"] = doc.value_date
	elif doc.doctype == "Loan Disbursement" and doc.get("disbursement_date"):
		gl_dict["value_date"] = doc.disbursement_date
	elif doc.doctype == "Loan Interest Accrual":
		gl_dict["value_date"] = doc.posting_date
	elif doc.get("demand_date"):
		gl_dict["value_date"] = doc.demand_date
