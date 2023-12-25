from lending.install import LOAN_CUSTOM_FIELDS, create_custom_fields


def execute():
	create_custom_fields(LOAN_CUSTOM_FIELDS, ignore_validate=True)
