from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	create_accounting_dimensions_for_doctype,
)

from lending.hooks import accounting_dimension_doctypes


def execute():
	for doctype in accounting_dimension_doctypes:
		create_accounting_dimensions_for_doctype(doctype)
