def add_ignore_linked_doctypes_for_jv(doc, method):
	existing = getattr(doc, 'ignore_linked_doctypes', ())
	lending_doctypes = ("Loan", "Loan Transfer", "Loan Interest Accrual", "Journal Entry")
	if existing:
		doc.ignore_linked_doctypes = existing + lending_doctypes
	else:
		doc.ignore_linked_doctypes = lending_doctypes