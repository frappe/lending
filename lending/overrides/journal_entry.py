def add_ignore_linked_doctypes_for_jv(doc, method):
<<<<<<< HEAD
	existing = getattr(doc, "ignore_linked_doctypes", ())
	lending_doctypes = ("Loan", "Loan Transfer", "Loan Interest Accrual")
=======
	existing = getattr(doc, 'ignore_linked_doctypes', ())
	lending_doctypes = ("Loan", "Loan Transfer", "Loan Interest Accrual", "Journal Entry")
>>>>>>> f0f36e1e (fix: add Journal Entry to ignore list during Journal Entry cancellation)
	if existing:
		doc.ignore_linked_doctypes = existing + lending_doctypes
	else:
		doc.ignore_linked_doctypes = lending_doctypes
