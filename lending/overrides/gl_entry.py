def update_value_date_in_gl_dict(doc, gl_dict):
	if doc.get("value_date"):
		gl_dict["value_date"] = doc.value_date
	elif doc.get("disbursement_date"):
		gl_dict["value_date"] = doc.disbursement_date
	elif doc.get("accrual_date"):
		gl_dict["value_date"] = doc.accrual_date
	elif doc.get("demand_date"):
		gl_dict["value_date"] = doc.demand_date
