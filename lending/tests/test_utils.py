import frappe
from frappe.utils import now_datetime

from erpnext.setup.utils import enable_all_roles_and_domains

from lending.loan_management.doctype.loan.utils import (
	create_loan_accounts,
	set_loan_accrual_frequency,
	set_loan_settings_in_company,
	setup_loan_demand_offset_order,
)


def before_tests():
	frappe.clear_cache()
	# complete setup if missing
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = now_datetime().year

	frappe.defaults.set_global_defaults("default_company", "_Test Company")
	frappe.defaults.set_global_defaults("default_currency", "INR")
	frappe.defaults.set_global_defaults("country", "India")

	if not frappe.get_list("Company"):
		setup_complete(
			{
				"currency": "INR",
				"full_name": "Test User",
				"company_name": "_Test Company",
				"timezone": "Asia/Kolkata",
				"company_abbr": "_TC",
				"industry": "Manufacturing",
				"country": "India",
				"fy_start_date": f"{year}-01-01",
				"fy_end_date": f"{year}-12-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@erpnext.com",
				"password": "test",
				"chart_of_accounts": "Standard",
			}
		)

	enable_all_roles_and_domains()
	set_loan_settings_in_company()
	create_loan_accounts()
	setup_loan_demand_offset_order()
	set_loan_accrual_frequency("Monthly")

	frappe.db.commit()  # nosemgrep
