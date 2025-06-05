def update_value_date_in_gl_dict(doc, gl_dict):
	if doc.get("value_date"):
		gl_dict["value_date"] = doc.value_date
